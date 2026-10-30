#!/usr/bin/env python3
"""Validated, atomic SQLite backups. Keeps the newest 14 snapshots by default."""
import os
import sqlite3
import tempfile
import time
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def validate(con):
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"projects", "cards"} <= tables or con.execute("PRAGMA user_version").fetchone()[0] < 1:
        raise ValueError("not an initialized Pulse database")
    if con.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise ValueError("database integrity check failed")
    if con.execute("PRAGMA foreign_key_check").fetchone():
        raise ValueError("database foreign key check failed")


def backup_database(source, destination, keep=14):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_file():
        raise FileNotFoundError("Pulse database does not exist; no backup created")
    if keep < 1:
        raise ValueError("keep must be positive")
    # mode=ro is essential: sqlite3.connect(path) silently creates missing files.
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
        validate(src)
        destination.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(destination, 0o700)
        fd, pending = tempfile.mkstemp(prefix=".pulse-backup-", suffix=".tmp", dir=destination)
        os.close(fd)
        try:
            with closing(sqlite3.connect(pending)) as target:
                src.backup(target)
                validate(target)
            with open(pending, "rb") as f:
                os.fsync(f.fileno())
            stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
            out = destination / f"pulse-{stamp}-{Path(pending).stem.removeprefix('.pulse-backup-')}.db"
            os.replace(pending, out)
            if os.name == "posix":
                directory_fd = os.open(destination, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            if os.path.exists(pending):
                os.unlink(pending)
    snapshots = sorted(destination.glob("pulse-*.db"), key=lambda f: (f.stat().st_mtime_ns, f.name))
    for item in snapshots:
        os.chmod(item, 0o600)
    for old in snapshots[:-keep]:
        if old != source and old != out:
            old.unlink()
    return out


def main():
    source = os.environ.get("PULSE_DB") or ROOT / "data" / "pulse.db"
    destination = os.environ.get("PULSE_BACKUP_DIR") or ROOT / "backups"
    try:
        out = backup_database(source, destination)
    except (OSError, sqlite3.Error, ValueError) as ex:
        raise SystemExit(f"Backup failed: {ex}")
    print(f"backup written to {out}")


if __name__ == "__main__":
    main()
