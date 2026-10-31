"""Upgrade, restore, credential preservation and durable delivery regression tests."""
import contextlib
import io
import json
import os
import runpy
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from test_pulse import ROOT, server, wait_jobs
import backup


class IsolatedDatabase(unittest.TestCase):
    def setUp(self):
        wait_jobs()
        self.temp = tempfile.TemporaryDirectory(prefix="pulse-storage-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "pulse.db"
        self.db_patch = patch.object(server, "DB_PATH", self.path)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.addCleanup(server.flush_deferred, False)

    def read(self, query, args=()):
        with contextlib.closing(server.db()) as con:
            return con.execute(query, args).fetchall()


class MigrationTests(IsolatedDatabase):
    def test_upgrade_retains_but_hides_ambiguous_legacy_history(self):
        with contextlib.closing(sqlite3.connect(self.path)) as con:
            con.executescript((ROOT / "tests/fixtures/schema-v4.sql").read_text())
            con.execute("INSERT INTO projects(slug,name,created_at,updated_at) VALUES('p','P',1,1)")
            con.execute("INSERT INTO todos(id,title,private,created_at,updated_at) VALUES(1,'Private todo',1,1,1)")
            con.execute("INSERT INTO reminders(id,text,at,todo_id,created_at) VALUES(1,'Linked reminder',1,1,1)")
            con.execute("INSERT INTO notifications(ts,kind,title) VALUES(1,'reminder','Legacy reminder')")
            con.execute("INSERT INTO updates(project,ts,author,text) VALUES('p',1,'owner','Todo done: old private title')")
            con.commit()
        server.init_db()
        server.init_db()  # restart must not replay migrations
        self.assertEqual(self.read("PRAGMA user_version")[0][0], 9)
        self.assertEqual(self.read("SELECT private FROM reminders")[0][0], 1)
        self.assertEqual(self.read("SELECT private FROM notifications")[0][0], 1)
        self.assertEqual(self.read("SELECT COUNT(*) FROM notifications")[0][0], 1)
        with contextlib.closing(server.db()) as con:
            p = con.execute("SELECT * FROM projects").fetchone()
            self.assertEqual(server.project_out(con, p, full=True)["updates"], [])
            self.assertEqual(len(server.project_out(con, p, full=True, role="user")["updates"]), 1)
        self.assertEqual(self.read("PRAGMA integrity_check")[0][0], "ok")
        self.assertEqual(self.read("PRAGMA foreign_key_check"), [])

    @unittest.skipUnless(os.name == "posix", "POSIX file modes")
    def test_database_and_sidecars_are_private(self):
        self.path.touch(mode=0o644)
        server.init_db()
        with contextlib.closing(server.db()) as con:
            con.execute("INSERT INTO projects(slug,name,created_at,updated_at) VALUES('p','P',1,1)")
            con.commit()
            for name in (self.path, Path(str(self.path) + "-wal"), Path(str(self.path) + "-shm")):
                if name.exists():
                    self.assertEqual(name.stat().st_mode & 0o777, 0o600, name)


class BackupTests(IsolatedDatabase):
    def test_missing_or_empty_source_fails_without_creating_source(self):
        with self.assertRaises(FileNotFoundError):
            backup.backup_database(self.path, self.root / "backups")
        self.assertFalse(self.path.exists())
        self.path.touch()
        with self.assertRaises(ValueError):
            backup.backup_database(self.path, self.root / "backups")
        self.assertFalse((self.root / "backups").exists())

    def test_cli_reports_missing_source_as_failure(self):
        result = subprocess.run([sys.executable, str(ROOT / "backup.py")], capture_output=True, text=True,
                                env={**os.environ, "PULSE_DB": str(self.path), "PULSE_BACKUP_DIR": str(self.root / "backups")})
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("backup written", result.stdout)
        self.assertFalse(self.path.exists())

    def test_live_backup_restore_retention_and_failure_atomicity(self):
        server.init_db()
        with contextlib.closing(server.db()) as con:
            con.execute("INSERT INTO projects(slug,name,created_at,updated_at) VALUES('restore','Restore marker',1,1)")
            con.commit()
            first = backup.backup_database(self.path, self.root / "backups", keep=2)
            second = backup.backup_database(self.path, self.root / "backups", keep=2)
            self.assertNotEqual(first, second)
            with contextlib.closing(sqlite3.connect(second)) as restored:
                self.assertEqual(restored.execute("SELECT name FROM projects").fetchone()[0], "Restore marker")
                backup.validate(restored)
            original = backup.validate
            calls = []
            def fail_target(db):
                calls.append(1)
                if len(calls) == 2:
                    raise ValueError("simulated incomplete snapshot")
                return original(db)
            with patch.object(backup, "validate", side_effect=fail_target):
                with self.assertRaises(ValueError):
                    backup.backup_database(self.path, self.root / "backups", keep=2)
            self.assertTrue(first.exists())
            self.assertTrue(second.exists())
            self.assertEqual(list((self.root / "backups").glob("*.tmp")), [])
            third = backup.backup_database(self.path, self.root / "backups", keep=2)
            self.assertTrue(third.exists())
            self.assertEqual(len(list((self.root / "backups").glob("pulse-*.db"))), 2)
            if os.name == "posix":
                self.assertEqual(third.stat().st_mode & 0o777, 0o600)
                self.assertEqual(third.parent.stat().st_mode & 0o777, 0o700)


class CredentialTests(unittest.TestCase):
    def test_cli_and_mcp_select_explicit_token_file(self):
        with tempfile.TemporaryDirectory(prefix="pulse-profile-test-") as directory:
            token = Path(directory) / "token"
            token.write_text("profile-token")
            for client in ("pulse", "pulse_mcp.py"):
                with patch.dict(os.environ, {"PULSE_TOKEN": "", "PULSE_TOKEN_FILE": str(token)}):
                    namespace = runpy.run_path(str(ROOT / client), run_name="test_client")
                    self.assertEqual(namespace["token"](), "profile-token")
                    with patch.dict(os.environ, {"PULSE_TOKEN": "environment-wins"}):
                        self.assertEqual(namespace["token"](), "environment-wins")

    def test_init_preserves_other_instance_and_explicit_profile_works(self):
        with tempfile.TemporaryDirectory(prefix="pulse-init-test-") as directory:
            root = Path(directory)
            token = root / ".config/pulse/token"
            token.parent.mkdir(parents=True)
            token.write_text("existing-instance-sentinel")
            config = root / "config.json"
            output = io.StringIO()
            with patch.object(Path, "home", return_value=root), patch.object(server, "CONFIG_PATH", config), \
                 patch.dict(os.environ, {"PULSE_TOKEN_FILE": ""}), patch.object(sys.stdin, "isatty", return_value=False), \
                 contextlib.redirect_stdout(output):
                server.cmd_init()
                self.assertEqual(token.read_text(), "existing-instance-sentinel")
                profile = root / "profiles/second-token"
                with patch.dict(os.environ, {"PULSE_TOKEN_FILE": str(profile)}):
                    server.cmd_init()
            self.assertIn(profile.read_text(), json.loads(config.read_text())["tokens"])
            self.assertNotIn(profile.read_text(), output.getvalue())
            if os.name == "posix":
                self.assertEqual(profile.stat().st_mode & 0o777, 0o600)
                self.assertEqual(config.stat().st_mode & 0o777, 0o600)


class DeliveryTests(IsolatedDatabase):
    def setUp(self):
        super().setUp()
        server.init_db()

    def create_job(self):
        with contextlib.closing(server.db()) as con, con:
            rid = server.create_reminder(con, {"text": "Private delivery", "in_minutes": 0, "private": True}, "owner", "user")["id"]
            nid = server.notify(con, "reminder", "Private delivery", private=True, reminder_id=rid)
        server.flush_deferred(False)  # simulate a restart before the in-memory job runs
        return nid, rid

    def state(self, nid):
        return dict(self.read("SELECT * FROM notifications WHERE id=?", (nid,))[0])

    def make_due(self, nid):
        with contextlib.closing(server.db()) as con, con:
            con.execute("UPDATE notifications SET next_attempt_at=0 WHERE id=?", (nid,))
            con.execute("UPDATE notification_deliveries SET lease_until=0 WHERE notification_id=?", (nid,))

    def test_outage_retries_and_does_not_expose_exception_secrets(self):
        nid, _ = self.create_job()
        with patch.object(server, "telegram_send", side_effect=RuntimeError("fake-bot-token-must-not-leak")):
            server.deliver_notification(nid)
        state = self.state(nid)
        self.assertEqual((state["delivery_status"], state["delivered"], state["attempts"]), ("retrying", 0, 1))
        self.assertNotIn("fake-bot-token", json.dumps(state))
        with patch.object(server, "telegram_send") as send:
            server.retry_notifications()
            send.assert_not_called()
            self.make_due(nid)
            server.retry_notifications()
            send.assert_called_once()
            server.retry_notifications()
            send.assert_called_once()
        self.assertEqual(self.state(nid)["delivery_status"], "delivered")
        self.assertEqual(self.read("SELECT * FROM notification_deliveries"), [])

    def test_pending_delivery_survives_new_process(self):
        nid, _ = self.create_job()
        config = self.root / "config.json"
        config.write_text(json.dumps({"telegram": {"enabled": True}}))
        subprocess.run([sys.executable, "-c", "import server; server.telegram_send=lambda text: None; server.retry_notifications()"],
                       cwd=ROOT, env={**os.environ, "PULSE_CONFIG": str(config), "PULSE_DB": str(self.path)}, check=True)
        self.assertEqual(self.state(nid)["delivered"], 1)

    def test_lease_prevents_concurrent_duplicate_sends_and_recovers_crash(self):
        nid, _ = self.create_job()
        entered, release = threading.Event(), threading.Event()
        def send(_):
            entered.set()
            self.assertTrue(release.wait(3))
        with patch.object(server, "telegram_send", side_effect=send) as sender, ThreadPoolExecutor(2) as pool:
            first = pool.submit(server.deliver_notification, nid)
            self.assertTrue(entered.wait(3))
            pool.submit(server.deliver_notification, nid).result(3)
            release.set()
            first.result(3)
            sender.assert_called_once()
        other, _ = self.create_job()
        with contextlib.closing(server.db()) as con, con:
            con.execute("UPDATE notifications SET delivery_status='delivering', attempts=1 WHERE id=?", (other,))
            con.execute("UPDATE notification_deliveries SET lease_until=? WHERE notification_id=?", (server.now() + 120, other))
        with patch.object(server, "telegram_send") as sender:
            server.retry_notifications()
            sender.assert_not_called()
            self.make_due(other)
            server.retry_notifications()
            sender.assert_called_once()

    def test_cancellation_and_exhaustion(self):
        nid, rid = self.create_job()
        with contextlib.closing(server.db()) as con, con:
            reminder = con.execute("SELECT * FROM reminders WHERE id=?", (rid,)).fetchone()
            server.patch_reminder(con, reminder, {"status": "cancelled"}, "user")
        with patch.object(server, "telegram_send") as sender:
            server.retry_notifications()
            sender.assert_not_called()
        self.assertEqual(self.state(nid)["delivery_status"], "cancelled")
        failed, _ = self.create_job()
        with patch.object(server, "telegram_send", side_effect=RuntimeError("offline")) as sender:
            for _ in range(server.DELIVERY_ATTEMPTS):
                self.make_due(failed)
                server.retry_notifications()
            server.retry_notifications()
            self.assertEqual(sender.call_count, server.DELIVERY_ATTEMPTS)
        self.assertEqual(self.state(failed)["delivery_status"], "failed")
        self.assertEqual(self.read("SELECT * FROM notification_deliveries"), [])


class IntegrationRegressionTests(IsolatedDatabase):
    def test_github_outage_does_not_advance_sync_or_lose_cards(self):
        server.init_db()
        with contextlib.closing(server.db()) as con, con:
            con.execute("INSERT INTO projects(slug,name,github_repo,gh_synced_at,created_at,updated_at) "
                        "VALUES('fixture','Fixture','example/fixture',100,1,1)")
            server.save_card(con, "fixture", None, {"title": "Preserved card"}, "tester")
        with patch.object(server, "gh", side_effect=RuntimeError("simulated outage")):
            with self.assertRaises(RuntimeError):
                server.gh_sync_project("fixture")
        self.assertEqual(self.read("SELECT gh_synced_at FROM projects")[0][0], 100)
        self.assertEqual(self.read("SELECT title FROM cards")[0][0], "Preserved card")
        self.assertEqual(len(self.read("SELECT * FROM cards")), 1)

    def test_daily_repeat_preserves_local_time_across_dst(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        zone = ZoneInfo("Europe/Lisbon")
        before = datetime(2026, 3, 28, 9, 0, tzinfo=zone)
        with patch.object(server, "TZ", zone), patch.object(server.time, "time", return_value=before.timestamp() + 1):
            next_time = server.next_occurrence(int(before.timestamp()), "daily")
        after = datetime.fromtimestamp(next_time, zone)
        self.assertEqual((after.day, after.hour, after.minute), (29, 9, 0))
        self.assertEqual(next_time - int(before.timestamp()), 23 * 3600)
