"""Reversible effects (Scope, JsonSnapshot) plus token hot-reload, end to end.

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


class JsonSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name, "config.json")
        self.write({"tokens": {"a": "alpha"}})

    def tearDown(self):
        self.dir.cleanup()

    def write(self, obj):
        tmp = Path(self.path.parent, ".tmp-write")
        tmp.write_text(json.dumps(obj))
        os.replace(tmp, self.path)  # same atomic replace as server.save_config

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


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TokenHotReloadTest(unittest.TestCase):
    """A token added while the server runs must work on the very next request."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.port = _free_port()
        self.cfg_path = Path(self.dir.name, "config.json")
        self.cfg = {"host": "127.0.0.1", "port": self.port, "timezone": "UTC", "secret": "s" * 64,
                    "tokens": {"first-token": "first"}, "telegram": {"enabled": False}}
        self._save()
        env = {**os.environ, "PULSE_CONFIG": str(self.cfg_path),
               "PULSE_DB": str(Path(self.dir.name, "pulse.db"))}
        self.proc = subprocess.Popen([sys.executable, str(ROOT / "server.py"), "serve"], env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self._wait_healthy()

    def tearDown(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.proc.stdout.close()
        self.proc.stderr.close()
        self.dir.cleanup()

    def _save(self):
        tmp = Path(self.dir.name, ".pulse-config-test")
        tmp.write_text(json.dumps(self.cfg))
        os.replace(tmp, self.cfg_path)

    def _wait_healthy(self):
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

    def _status(self, token, path="/api/projects"):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}")
        req.add_header("Authorization", "Bearer " + token)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def test_added_token_works_without_restart(self):
        self.assertEqual(self._status("first-token"), 200)
        self.assertEqual(self._status("second-token"), 401)

        # exactly what `python3 server.py add-token second` does to the file
        self.cfg["tokens"]["second-token"] = "second"
        self._save()

        self.assertEqual(self._status("second-token"), 200)
        self.assertEqual(self._status("first-token"), 200)  # the old token still works
        self.assertEqual(self._status("bogus-token"), 401)

    def test_removed_token_stops_working_without_restart(self):
        self.assertEqual(self._status("first-token"), 200)
        del self.cfg["tokens"]["first-token"]
        self._save()
        self.assertEqual(self._status("first-token"), 401)


if __name__ == "__main__":
    unittest.main()
