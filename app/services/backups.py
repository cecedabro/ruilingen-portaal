"""Hourly copies of the SQLite database, next to it on the same volume (/data/backups).

They cover the most likely accident: a bug or a mistake that damages data. You go back to the
last good hour instead of last night's Longhorn backup. They do NOT cover losing the volume
itself; the nightly Longhorn backup (NAS + off-site) carries these files along for that.

`VACUUM INTO` writes a consistent, compact copy while the app keeps running (WAL mode), and the
copy is a plain .db file: open it with any sqlite3, no Longhorn needed.
"""

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

log = logging.getLogger("ruilingen")

PREFIX = "ruilingen-"


def sqlite_path(database_url: str) -> Path | None:
    """The database file behind a sqlite:/// URL, or None for anything else (or in-memory)."""
    if not database_url.startswith("sqlite:///"):
        return None
    path = database_url.removeprefix("sqlite:///")
    return None if path in {"", ":memory:"} else Path(path)


def snapshot(db_file: Path, backup_dir: Path, keep: int, now: datetime) -> Path:
    """Copy the database to backup_dir/ruilingen-YYYYMMDD-HHMMSS.db and keep the newest `keep`."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"{PREFIX}{now:%Y%m%d-%H%M%S}.db"
    partial = target.with_suffix(".partial")
    partial.unlink(missing_ok=True)
    conn = sqlite3.connect(db_file)
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("VACUUM INTO ?", (str(partial),))
    finally:
        conn.close()
    partial.replace(target)  # a half-written copy never looks like a real backup
    for old in sorted(backup_dir.glob(f"{PREFIX}*.db"))[:-keep]:
        old.unlink(missing_ok=True)
    return target


def list_snapshots(backup_dir: Path) -> list[Path]:
    """Oldest first."""
    return sorted(backup_dir.glob(f"{PREFIX}*.db")) if backup_dir.is_dir() else []
