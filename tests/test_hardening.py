"""Release-blocking security regressions, using the isolated HTTP test server."""
import json
import time
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from test_pulse import call, server, RSA, TOKEN, wait_jobs


def owner(method, path, body=None):
    return call(method, path, body, token=None,
                headers={"Cookie": "pulse_session=" + server.make_session()})


class AccessBoundaryTests(unittest.TestCase):
    def test_unknown_api_root_and_invalid_body_size(self):
        self.assertEqual(call("POST", "/api", {})["HTTP"], 404)
        self.assertEqual(call("POST", "/api/notes", {}, headers={"Content-Length": "-1"})["HTTP"], 413)

    def test_machine_jwt_never_grants_owner(self):
        rsa = RSA()
        server._certs.update({"at": time.time(), "keys": {"k1": rsa.jwk}})
        claims = {"aud": ["AUD"], "iss": "https://team.cloudflareaccess.com", "type": "app",
                  "exp": time.time() + 60, "common_name": "test-service.access", "sub": ""}
        note = owner("POST", "/api/notes", {"body": "Machine must not read this", "private": True})
        for payload in (claims, {**claims, "email": "fake@example.com"},
                        {k: v for k, v in claims.items() if k not in ("common_name", "sub")}):
            headers = {"Cf-Access-Jwt-Assertion": rsa.jwt(payload)}
            self.assertEqual(call("GET", "/api/me", token=None, headers=headers)["HTTP"], 401)
            self.assertEqual(call("GET", f"/api/notes/{note['id']}", token=None, headers=headers)["HTTP"], 401)
            self.assertEqual(call("GET", "/api/me", token=TOKEN, headers=headers)["role"], "agent")
        human = {k: v for k, v in claims.items() if k != "common_name"}
        human.update(email="sam@example.com", sub="human-id")
        headers = {"Cf-Access-Jwt-Assertion": rsa.jwt(human)}
        self.assertEqual(call("GET", f"/api/notes/{note['id']}", token=None, headers=headers)["id"], note["id"])
        headers = {"Cf-Access-Jwt-Assertion": rsa.jwt({**human, "nbf": time.time() + 3600})}
        self.assertEqual(call("GET", "/api/me", token=None, headers=headers)["HTTP"], 401)

    def test_spoofed_proxy_headers_cannot_reset_rate_limit(self):
        server._login_fails.clear()
        try:
            for i in range(10):
                self.assertEqual(call("POST", "/api/login", {"password": "bad"}, token=None,
                                      headers={"Cf-Connecting-Ip": f"198.51.100.{i}",
                                               "X-Forwarded-For": f"203.0.113.{i}"})["HTTP"], 401)
            self.assertEqual(call("POST", "/api/login", {"password": "correct horse"}, token=None,
                                  headers={"Cf-Connecting-Ip": "192.0.2.100"})["HTTP"], 429)
        finally:
            server._login_fails.clear()

    def test_trusted_proxy_chain_and_header_selection(self):
        handler = object.__new__(server.Handler)
        handler.client_address = ("127.0.0.1", 1234)
        handler.headers = {"X-Forwarded-For": "198.51.100.99, 203.0.113.8", "Cf-Connecting-Ip": "192.0.2.9"}
        with patch.dict(server.CONFIG, {"trusted_proxies": ["127.0.0.1/32"], "client_ip_header": "X-Forwarded-For"}):
            self.assertEqual(handler.client_ip(), "203.0.113.8")
            handler.headers["X-Forwarded-For"] = "invalid"
            self.assertEqual(handler.client_ip(), "127.0.0.1")
        with patch.dict(server.CONFIG, {"trusted_proxies": ["127.0.0.1/32"], "client_ip_header": "Cf-Connecting-Ip"}):
            self.assertEqual(handler.client_ip(), "192.0.2.9")
            handler.client_address = ("203.0.113.1", 1234)
            self.assertEqual(handler.client_ip(), "203.0.113.1")


class PrivacyTests(unittest.TestCase):
    def setUp(self):
        self.slug = "privacy-" + uuid.uuid4().hex[:10]
        call("POST", "/api/projects", {"slug": self.slug, "name": "Privacy fixture"})

    def test_private_reminders_never_enter_agent_notifications(self):
        reminder = owner("POST", "/api/reminders", {"text": "Private notification marker", "private": True, "in_minutes": 0})
        before = call("GET", "/api/today")["unread_notifications"]
        server.fire_due_reminders()
        wait_jobs()
        notifications = owner("GET", "/api/notifications")
        notification = next(n for n in notifications if n["reminder_id"] == reminder["id"])
        self.assertNotIn(notification["id"], [n["id"] for n in call("GET", "/api/notifications")])
        self.assertEqual(call("GET", "/api/today")["unread_notifications"], before)
        for payload in ({"ids": [notification["id"]]}, {}):
            call("POST", "/api/notifications/read", payload)
            self.assertEqual(next(n for n in owner("GET", "/api/notifications") if n["id"] == notification["id"])["read"], 0)

    def test_nested_reminders_and_private_parent_authorization(self):
        todo = owner("POST", "/api/todos", {"title": "Public parent", "due": "today"})
        reminder = owner("POST", "/api/reminders", {"text": "Nested private marker", "private": True,
                                                    "todo_id": todo["id"], "in_minutes": 30})
        self.assertEqual(owner("GET", f"/api/todos/{todo['id']}")["reminders"][0]["id"], reminder["id"])
        self.assertEqual(call("GET", f"/api/todos/{todo['id']}")["reminders"], [])
        self.assertNotIn("Nested private marker", json.dumps(call("GET", "/api/today")))
        for method, body in (("GET", None), ("PATCH", {"text": "changed"}), ("DELETE", None)):
            self.assertEqual(call(method, f"/api/reminders/{reminder['id']}", body)["HTTP"], 404)
        owner("PATCH", f"/api/todos/{todo['id']}", {"private": True})
        self.assertEqual(call("POST", "/api/reminders", {"text": "probe", "todo_id": todo["id"], "in_minutes": 30})["HTTP"], 404)
        inherited = owner("POST", "/api/reminders", {"text": "inherits privacy", "todo_id": todo["id"], "in_minutes": 30})
        self.assertEqual(inherited["private"], 1)
        self.assertEqual(owner("PATCH", f"/api/reminders/{inherited['id']}", {"private": False})["HTTP"], 400)

    def test_privacy_transition_hides_existing_history(self):
        marker = "Private history " + self.slug
        todo = owner("POST", "/api/todos", {"title": marker, "project": self.slug, "remind_at": "in 0m"})
        server.fire_due_reminders()
        wait_jobs()
        owner("PATCH", f"/api/todos/{todo['id']}", {"status": "done"})
        self.assertIn(marker, json.dumps(call("GET", f"/api/projects/{self.slug}")))
        owner("PATCH", f"/api/todos/{todo['id']}", {"private": True})
        for path in (f"/api/projects/{self.slug}", "/api/projects", "/api/notifications", "/api/reminders?status=all", "/api/todos?view=all"):
            self.assertNotIn(marker, json.dumps(call("GET", path)), path)
        self.assertIn(marker, json.dumps(owner("GET", f"/api/projects/{self.slug}")))
        # Updates returned by mutation endpoints must also filter private history.
        self.assertNotIn(marker, json.dumps(call("PATCH", f"/api/projects/{self.slug}", {"summary": "update"})))
        self.assertNotIn(marker, json.dumps(call("POST", f"/api/projects/{self.slug}/updates", {"text": "public update"})))
        owner("PATCH", f"/api/todos/{todo['id']}", {"private": False})
        self.assertNotIn(marker, json.dumps(call("GET", "/api/notifications")))

    def test_private_completion_and_promotion(self):
        marker = "Private completed " + self.slug
        todo = owner("POST", "/api/todos", {"title": marker, "project": self.slug, "private": True})
        self.assertEqual(owner("POST", f"/api/todos/{todo['id']}/promote", {})["HTTP"], 400)
        owner("PATCH", f"/api/todos/{todo['id']}", {"status": "done"})
        self.assertNotIn(marker, json.dumps(call("GET", f"/api/projects/{self.slug}")))
        self.assertIn(marker, json.dumps(owner("GET", f"/api/projects/{self.slug}")))

    def test_concurrent_agent_patch_cannot_undo_owner_privacy(self):
        todo = owner("POST", "/api/todos", {"title": "Concurrent privacy"})
        entered, release, owner_started = threading.Event(), threading.Event(), threading.Event()
        original = server.save_todo
        def pause_agent(con, item, body, who, role):
            if role == "agent" and item and item["id"] == todo["id"]:
                entered.set()
                if not release.wait(3):
                    raise RuntimeError("test timed out")
            return original(con, item, body, who, role)
        def make_private():
            owner_started.set()
            return owner("PATCH", f"/api/todos/{todo['id']}", {"private": True})
        with patch.object(server, "save_todo", side_effect=pause_agent), ThreadPoolExecutor(2) as pool:
            agent = pool.submit(call, "PATCH", f"/api/todos/{todo['id']}", {"notes": "agent update"})
            self.assertTrue(entered.wait(3))
            human = pool.submit(make_private)
            self.assertTrue(owner_started.wait(3))
            try:
                # The owner must wait for the already-authorized agent transaction.
                time.sleep(0.1)
                self.assertFalse(human.done())
            finally:
                release.set()
            self.assertIn("id", agent.result(3))
            self.assertEqual(human.result(3)["private"], 1)
        self.assertEqual(call("GET", f"/api/todos/{todo['id']}")["HTTP"], 404)

    def test_scheduler_serializes_with_privacy_changes(self):
        reminder = owner("POST", "/api/reminders", {"text": "Scheduler privacy", "in_minutes": 0})
        entered, release, owner_started = threading.Event(), threading.Event(), threading.Event()
        original = server.db
        def connect():
            con = original()
            if threading.current_thread().name.startswith("privacy-scheduler"):
                def trace(sql):
                    if sql.startswith("SELECT * FROM reminders WHERE status='pending'"):
                        entered.set()
                        release.wait(3)
                con.set_trace_callback(trace)
            return con
        def make_private():
            owner_started.set()
            return owner("PATCH", f"/api/reminders/{reminder['id']}", {"private": True})
        with patch.object(server, "db", side_effect=connect), ThreadPoolExecutor(1, thread_name_prefix="privacy-scheduler") as scheduler, ThreadPoolExecutor(1) as writers:
            fired = scheduler.submit(server.fire_due_reminders)
            self.assertTrue(entered.wait(3))
            human = writers.submit(make_private)
            self.assertTrue(owner_started.wait(3))
            try:
                time.sleep(0.1)
                self.assertFalse(human.done())
            finally:
                release.set()
            fired.result(3)
            self.assertEqual(human.result(3)["private"], 1)
        wait_jobs()
        self.assertNotIn("Scheduler privacy", json.dumps(call("GET", "/api/notifications")))


class NotificationLinkTests(unittest.TestCase):
    def test_api_rejects_script_urls(self):
        for link in ("javascript:void(0)", "JaVaScRiPt:alert(1)", "data:text/html,bad", "//example.com",
                     "java\nscript:void(0)", "https://example.com\\@evil", "https:"):
            self.assertEqual(call("POST", "/api/notify", {"title": "Link test", "link": link})["HTTP"], 400, link)
        for link in ("", "#/todos/1", "https://example.com/path?q=x&y=2", "http://localhost:4100/"):
            self.assertIn("id", call("POST", "/api/notify", {"title": "Link test", "link": link}), link)
