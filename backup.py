#!/usr/bin/env python3
"""Consistent SQLite backup of the Pulse database; keeps the newest 14 copies in backups/."""
import os, sqlite3, time
from pathlib import Path

root = Path(__file__).resolve().parent
db = Path(os.environ.get("PULSE_DB") or root / "data" / "pulse.db")
dest = root / "backups"
dest.mkdir(exist_ok=True)
out = dest / time.strftime("pulse-%Y%m%d.db")
src = sqlite3.connect(db)
with sqlite3.connect(out) as d:
    src.backup(d)
src.close()
for old in sorted(dest.glob("pulse-*.db"))[:-14]:
    old.unlink()
print(f"backup written to {out}")
