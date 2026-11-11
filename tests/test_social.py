"""Social posts pipeline tests: drafts, owner-only approval, scheduling, results, media, flag.

Run: python3 -m unittest tests.test_social -v   (requires the shared fixture server from test_pulse)
"""
import base64, json, time, unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_pulse
from test_pulse import call, set_config

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 40).decode()
OWNER = None  # session cookie, established in setUpClass


def owner_call(method, path, body=None):
    return call(method, path, body, token=None, headers={"Cookie": OWNER})


def _login():
    global OWNER
    code, _, headers = test_pulse.call("POST", "/api/login", {"password": "correct horse"}, token=None, raw=True)
    assert code == 200
    OWNER = headers["Set-Cookie"].split(";")[0]


class TestSocial(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _login()
        set_config(social_posting=True)

    @classmethod
    def tearDownClass(cls):
        set_config(social_posting=False)

    def test_flag_gates_routes(self):
        set_config(social_posting=False)
        try:
            self.assertEqual(call("GET", "/api/social")["HTTP"], 404)
        finally:
            set_config(social_posting=True)
        self.assertIsInstance(call("GET", "/api/social"), list)

    def test_me_exposes_flag(self):
        self.assertTrue(call("GET", "/api/me")["social_posting"])

    def test_full_pipeline(self):
        p = call("POST", "/api/social", {"text": "Hello from the pipeline", "platform": "linkedin"})
        self.assertEqual(p["status"], "draft")
        pid = p["id"]

        # agents may not approve
        self.assertEqual(call("POST", f"/api/social/{pid}/approve")["HTTP"], 403)
        # ...and may not schedule before approval
        self.assertEqual(call("POST", f"/api/social/{pid}/schedule", {"due": "in 1h"})["HTTP"], 400)

        # the owner approves...
        out = owner_call("POST", f"/api/social/{pid}/approve")
        self.assertEqual(out["status"], "approved")
        # ...the agent schedules...
        out = call("POST", f"/api/social/{pid}/schedule", {"due": "in 1h"})
        self.assertEqual(out["status"], "scheduled")
        self.assertTrue(out["due_at"] > time.time())
        self.assertTrue(out["due_local"])

        # not due yet -> not listed
        self.assertFalse(call("GET", "/api/social/due"))
        # backdate -> due, then the scheduler (an agent) reports success
        import server
        con = server.db()
        with con:
            con.execute("UPDATE social_posts SET due_at=? WHERE id=?", (int(time.time()) - 5, pid))
        con.close()
        due = call("GET", "/api/social/due")
        self.assertEqual([d["id"] for d in due], [pid])
        out = call("POST", f"/api/social/{pid}/result", {"status": "posted", "posted_id": "urn:li:share:123"})
        self.assertEqual(out["status"], "posted")
        self.assertEqual(out["posted_id"], "urn:li:share:123")
        self.assertFalse(call("GET", "/api/social/due"))

    def test_agent_cannot_cancel_or_delete(self):
        p = call("POST", "/api/social", {"text": "hold me"})
        self.assertEqual(call("POST", f"/api/social/{p['id']}/cancel")["HTTP"], 403)
        self.assertEqual(call("DELETE", f"/api/social/{p['id']}")["HTTP"], 403)
        self.assertEqual(owner_call("POST", f"/api/social/{p['id']}/cancel")["status"], "cancelled")
        self.assertEqual(owner_call("DELETE", f"/api/social/{p['id']}")["deleted"], p["id"])

    def test_owner_can_schedule_approved(self):
        p = call("POST", "/api/social", {"text": "owner schedules too"})
        owner_call("POST", f"/api/social/{p['id']}/approve")
        out = owner_call("POST", f"/api/social/{p['id']}/schedule", {"due": "tomorrow 09:00"})
        self.assertEqual(out["status"], "scheduled")
        self.assertEqual(out["scheduled_by"], "owner")

    def test_media_roundtrip_and_limits(self):
        p = call("POST", "/api/social", {"text": "with image"})
        out = call("POST", f"/api/social/{p['id']}/media", {"filename": "pic.png", "data_b64": PNG})
        self.assertEqual(out["media"], [f"{p['id']}-0-pic.png"])
        got = call("GET", f"/api/social/{p['id']}/media/0")
        self.assertEqual(got["mime"], "image/png")
        self.assertEqual(base64.b64decode(got["data_b64"]), base64.b64decode(PNG))
        self.assertEqual(call("GET", f"/api/social/{p['id']}/media/5")["HTTP"], 404)
        # media cannot be added after approval
        owner_call("POST", f"/api/social/{p['id']}/approve")
        self.assertEqual(call("POST", f"/api/social/{p['id']}/media",
                              {"filename": "x.png", "data_b64": PNG})["HTTP"], 400)
        owner_call("DELETE", f"/api/social/{p['id']}")
        self.assertEqual(call("GET", f"/api/social/{p['id']}/media/0")["HTTP"], 404)

    def test_reject_bad_media_and_text(self):
        p = call("POST", "/api/social", {"text": "bad ext"})
        self.assertEqual(call("POST", f"/api/social/{p['id']}/media",
                              {"filename": "evil.exe", "data_b64": PNG})["HTTP"], 400)
        self.assertEqual(call("POST", "/api/social",
                              {"text": "x" * 3001, "platform": "linkedin"})["HTTP"], 400)
        self.assertEqual(call("POST", "/api/social", {"text": "ok", "platform": "mastodon"})["HTTP"], 400)
        self.assertEqual(call("POST", "/api/social", {"text": "x" * 281, "platform": "x"})["HTTP"], 400)
        self.assertEqual(call("POST", "/api/social", {"text": "ok", "platform": "x"})["status"], "draft")

    def test_scheduling_flow_guards(self):
        p = call("POST", "/api/social", {"text": "guards"})
        self.assertEqual(call("POST", f"/api/social/{p['id']}/result",
                              {"status": "posted"})["HTTP"], 400)
        owner_call("POST", f"/api/social/{p['id']}/approve")
        self.assertEqual(call("POST", f"/api/social/{p['id']}/schedule", {"due": "in 1h"})["status"], "scheduled")
        self.assertEqual(call("POST", f"/api/social/{p['id']}/result",
                              {"status": "published"})["HTTP"], 400)
        out = call("POST", f"/api/social/{p['id']}/result", {"status": "failed", "error": "expired token"})
        self.assertEqual(out["status"], "failed")
        self.assertEqual(out["error"], "expired token")
