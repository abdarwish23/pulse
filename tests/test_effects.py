"""Reversible effects (Scope, JsonSnapshot, LiveConfig), with live-reload end-to-end tests.

Run: python3 -m unittest discover -s tests -v
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import effects  # noqa: E402


class ScopeTests(unittest.TestCase):
    def test_disposes_in_reverse_order(self):
        order = []
        scope = effects.Scope("t")
        scope.effect(lambda: order.append("first"))
        scope.effect(lambda: order.append("second"))
        self.assertEqual(scope.dispose(), 2)
        self.assertEqual(order, ["second", "first"])

    def test_single_disposer_is_idempotent(self):
        calls = []
        scope = effects.Scope("t")
        dispose = scope.effect(lambda: calls.append(1))
        dispose()
        dispose()
        self.assertEqual(calls, [1])
        self.assertEqual(scope.dispose(), 0)  # nothing left to unwind

    def test_failing_effect_does_not_stop_the_others(self):
        calls = []

        def boom():
            raise RuntimeError("nope")

        scope = effects.Scope("t")
        scope.effect(lambda: calls.append("a"))
        scope.effect(boom)
        scope.effect(lambda: calls.append("c"))
        self.assertEqual(scope.dispose(), 3)
        self.assertEqual(calls, ["c", "a"])

    def test_child_scope_is_disposed_by_its_parent(self):
        calls = []
        parent = effects.Scope("parent")
        child = effects.Scope("child", parent=parent)
        child.effect(lambda: calls.append("child effect"))
        parent.dispose()
        self.assertEqual(calls, ["child effect"])
        self.assertTrue(child.disposed)

    def test_effect_after_disposal_runs_immediately(self):
        calls = []
        scope = effects.Scope("t")
        scope.dispose()
        scope.effect(lambda: calls.append("late"))
        self.assertEqual(calls, ["late"])
        self.assertEqual(len(scope), 0)

    def test_context_manager_is_an_effect(self):
        log = []

        class Res:
            def __enter__(self):
                log.append("enter")

            def __exit__(self, *exc):
                log.append("exit")

        scope = effects.Scope("t")
        scope.effect(Res())
        scope.dispose()
        self.assertEqual(log, ["enter", "exit"])

    def test_pending_labels_track_mounts(self):
        scope = effects.Scope("t")
        scope.effect(lambda: None, label="route:/api/x")
        scope.effect(lambda: None, label="job:reminders")
        self.assertEqual(scope.pending(), ["route:/api/x", "job:reminders"])
        self.assertEqual(len(scope), 2)


class _FileCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name, "config.json")
        self.write({"tokens": {"a": "alpha"}})

    def tearDown(self):
        self.dir.cleanup()

    def write(self, obj):
        tmp = Path(self.path.parent, ".tmp-write")
        tmp.write_text(json.dumps(obj))
        os.replace(tmp, self.path)  # the same atomic replace as server.save_config


class JsonSnapshotTests(_FileCase):
    def snap(self):
        return effects.JsonSnapshot(self.path, lambda cfg: dict((cfg or {}).get("tokens") or {}), default={})

    def test_reads_the_initial_value(self):
        self.assertEqual(self.snap().get(), {"a": "alpha"})

    def test_picks_up_a_change_without_restart(self):
        s = self.snap()
        before = s.reloads
        self.write({"tokens": {"a": "alpha", "b": "beta"}})
        self.assertEqual(s.get(), {"a": "alpha", "b": "beta"})
        self.assertGreater(s.reloads, before)

    def test_invalid_json_keeps_the_last_good_value(self):
        s = self.snap()
        self.path.write_text("{not json")
        self.assertEqual(s.get(), {"a": "alpha"})
        self.assertEqual(s.errors, 1)

    def test_broken_content_is_not_retried_on_every_read(self):
        s = self.snap()
        self.path.write_text("{not json")
        s.get()
        for _ in range(5):
            s.get()
        self.assertEqual(s.errors, 1)

    def test_missing_file_keeps_the_last_good_value(self):
        s = self.snap()
        self.path.unlink()
        self.assertEqual(s.get(), {"a": "alpha"})

    def test_no_reload_when_the_file_is_unchanged(self):
        s = self.snap()
        before = s.reloads
        for _ in range(5):
            s.get()
        self.assertEqual(s.reloads, before)

    def test_build_failure_keeps_the_last_good_value(self):
        s = effects.JsonSnapshot(self.path, lambda cfg: cfg["missing"]["key"], default="initial")
        self.assertEqual(s.get(), "initial")
        self.assertEqual(s.errors, 1)


class LiveConfigTests(_FileCase):
    def cfg(self, default=None):
        snap = effects.JsonSnapshot(self.path, lambda raw: dict(raw or {}), default=default or {})
        return effects.LiveConfig(snap)

    def test_reads_follow_the_file(self):
        cfg = self.cfg()
        self.assertEqual(cfg["tokens"], {"a": "alpha"})
        self.write({"tokens": {"a": "alpha"}, "public_url": "https://example.test"})
        self.assertEqual(cfg["public_url"], "https://example.test")
        self.assertEqual(cfg.get("missing", "fallback"), "fallback")
        self.assertIn("tokens", cfg)
        self.assertEqual(list(cfg.keys()), ["tokens", "public_url"])
        self.assertEqual(len(cfg), 2)

    def test_process_local_override_does_not_touch_the_file(self):
        cfg = self.cfg()
        cfg["port"] = 1
        self.assertEqual(cfg["port"], 1)
        self.assertEqual(cfg.overrides(), ["port"])
        self.assertEqual(json.loads(self.path.read_text())["tokens"], {"a": "alpha"})  # file unchanged
        del cfg["port"]
        self.assertNotIn("port", cfg.overrides())
        self.assertEqual(cfg["tokens"], {"a": "alpha"})

    def test_file_change_wins_over_an_override(self):
        cfg = self.cfg()
        cfg["public_url"] = "https://override.test"
        self.assertEqual(cfg["public_url"], "https://override.test")
        self.write({"tokens": {"a": "alpha"}, "public_url": "https://file.test"})
        self.assertEqual(cfg["public_url"], "https://file.test")
        self.assertEqual(cfg.overrides(), [])

    def test_mapping_helpers_used_by_patch_dict(self):
        import unittest.mock as mock
        cfg = self.cfg()
        with mock.patch.dict(cfg, {"trusted_proxies": ["127.0.0.1/32"]}):
            self.assertEqual(cfg["trusted_proxies"], ["127.0.0.1/32"])
            self.assertEqual(cfg["tokens"], {"a": "alpha"})
        self.assertNotIn("trusted_proxies", cfg)  # the override is gone again
        cfg.update({"port": 9})
        self.assertEqual(cfg.copy()["port"], 9)
        cfg.clear()
        self.assertEqual(cfg["tokens"], {"a": "alpha"})

    def test_malformed_file_keeps_the_last_good_config(self):
        cfg = self.cfg()
        self.path.write_text("{ broken")
        self.assertEqual(cfg["tokens"], {"a": "alpha"})


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _ServerCase(unittest.TestCase):
    """A real `server.py serve` subprocess with its own config file and database."""

    config = {}

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.port = _free_port()
        self.cfg_path = Path(self.dir.name, "config.json")
        self.cfg = {"host": "127.0.0.1", "port": self.port, "timezone": "UTC", "secret": "s" * 64,
                    "telegram": {"enabled": False}, **self.config}
        self.save()
        env = {**os.environ, "PULSE_CONFIG": str(self.cfg_path),
               "PULSE_DB": str(Path(self.dir.name, "pulse.db"))}
        self.proc = subprocess.Popen([sys.executable, str(ROOT / "server.py"), "serve"], env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.wait_healthy()

    def tearDown(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.proc.stdout.close()
        self.proc.stderr.close()
        self.dir.cleanup()

    def save(self):
        tmp = Path(self.dir.name, ".pulse-config-test")
        tmp.write_text(json.dumps(self.cfg))
        os.replace(tmp, self.cfg_path)  # exactly what `server.py add-token` does

    def wait_healthy(self):
        deadline = time.time() + 20
        while time.time() < deadline:
            if self.proc.poll() is not None:
                self.fail(f"server exited early: {self.proc.stderr.read()[-2000:]}")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/health", timeout=1):
                    return
            except Exception:
                time.sleep(0.05)
        self.fail("server did not become healthy")

    def request(self, path, token=None, method="GET"):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method)
        if token:
            req.add_header("Authorization", "Bearer " + token)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def status(self, path, token=None):
        return self.request(path, token)[0]


class TokenHotReloadTest(_ServerCase):
    """A token added while the server runs must work on the very next request."""

    config = {"tokens": {"first-token": "first"}}

    def test_added_token_works_without_restart(self):
        self.assertEqual(self.status("/api/projects", "first-token"), 200)
        self.assertEqual(self.status("/api/projects", "second-token"), 401)

        self.cfg["tokens"]["second-token"] = "second"  # `server.py add-token second`
        self.save()

        self.assertEqual(self.status("/api/projects", "second-token"), 200)
        self.assertEqual(self.status("/api/projects", "first-token"), 200)  # old token still valid
        self.assertEqual(self.status("/api/projects", "bogus-token"), 401)

    def test_removed_token_stops_working_without_restart(self):
        self.assertEqual(self.status("/api/projects", "first-token"), 200)
        del self.cfg["tokens"]["first-token"]
        self.save()
        self.assertEqual(self.status("/api/projects", "first-token"), 401)


class ConfigHotReloadTest(_ServerCase):
    """Any config value must be read from the file, not from start-up state."""

    config = {"tokens": {"first-token": "first"}, "github_poll_seconds": 300}

    def test_cloudflare_access_switch_flips_without_restart(self):
        self.assertEqual(self.request("/api/auth")[1]["cloudflare"], False)
        self.cfg["access_team"] = "team"
        self.cfg["access_aud"] = "aud"
        self.save()
        self.assertEqual(self.request("/api/auth")[1]["cloudflare"], True)

    def test_local_owner_trust_flips_without_restart(self):
        self.assertEqual(self.status("/api/me"), 401)  # no token, no password, no trust
        self.cfg["trust_localhost"] = True
        self.save()
        self.assertEqual(self.status("/api/me"), 200)
        self.cfg["trust_localhost"] = False
        self.save()
        self.assertEqual(self.status("/api/me"), 401)

    def test_malformed_config_does_not_lock_the_server_out(self):
        self.assertEqual(self.status("/api/projects", "first-token"), 200)
        self.cfg_path.write_text("{ broken json")
        self.assertEqual(self.status("/api/projects", "first-token"), 200)  # last good config kept


if __name__ == "__main__":
    unittest.main()
