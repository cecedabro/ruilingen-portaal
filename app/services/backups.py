"""Hourly copies of the SQLite database, next to it on the same volume (/data/backups).

They cover the most likely accident: a bug or a mistake that damages data. You go back to the
last good hour instead of last night's Longhorn backup. They do NOT cover losing the volume
itself; the nightly Longhorn backup (NAS + off-site) carries these files along for that.

Before a release that changes the schema, docker-entrypoint.sh adds a `-voor-migratie` copy.

`VACUUM INTO` writes a consistent, compact copy while the app keeps running (WAL mode), and the
copy is a plain .db file: open it with any sqlite3, no Longhorn needed.
"""

import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger("ruilingen")

PREFIX = "ruilingen-"


def sqlite_path(database_url: str) -> Path | None:
    """The database file behind a sqlite:/// URL, or None for anything else (or in-memory)."""
    if not database_url.startswith("sqlite:///"):
        return None
    path = database_url.removeprefix("sqlite:///")
    return None if path in {"", ":memory:"} else Path(path)


def snapshot(db_file: Path, backup_dir: Path, keep: int, now: datetime, tag: str = "") -> Path:
    """Copy the database to backup_dir/ruilingen-YYYYMMDD-HHMMSS[-tag].db and keep the newest
    `keep` copies (any tag)."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"{PREFIX}{now:%Y%m%d-%H%M%S}{'-' + tag if tag else ''}.db"
    partial = target.with_suffix(".partial")
    partial.unlink(missing_ok=True)
    conn = sqlite3.connect(db_file)
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("VACUUM INTO ?", (str(partial),))
    finally:
        conn.close()
    partial.replace(target)  # a half-written copy never looks like a real backup
    for old in list_snapshots(backup_dir)[:-keep]:
        old.unlink(missing_ok=True)
    return target


def migration_pending(db_file: Path, root: Path) -> bool:
    """Does `alembic upgrade head` have work to do on this file? (`root` holds alembic.ini)"""
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine

    script = ScriptDirectory.from_config(Config(str(root / "alembic.ini")))
    engine = create_engine(f"sqlite:///{db_file}")
    try:
        with engine.connect() as conn:
            current = set(MigrationContext.configure(conn).get_current_heads())
    finally:
        engine.dispose()
    return current != set(script.get_heads())


PRE_MIGRATION = "voor-migratie"


def before_migration(db_file: Path, backup_dir: Path, keep: int, now: datetime, root: Path) -> str:
    """Run by docker-entrypoint.sh before `alembic upgrade head`: copy the database when the
    release changes the schema, so a rollback has the exact state from before it. Skipped when
    there's no database yet, nothing to migrate, or such a copy was made in the last 15 minutes
    (a pod restarting over and over mustn't push the good hourly copies out)."""
    if not db_file.exists():
        return "geen database, niks te bewaren"
    if not migration_pending(db_file, root):
        return "geen migratie, geen extra kopie"
    since = f"{PREFIX}{now - timedelta(minutes=15):%Y%m%d-%H%M%S}"
    recent = [p for p in list_snapshots(backup_dir) if PRE_MIGRATION in p.name and p.name > since]
    if recent:
        return f"recente kopie gebruikt: {recent[-1].name}"
    return f"kopie voor migratie: {snapshot(db_file, backup_dir, keep, now, PRE_MIGRATION)}"


def list_snapshots(backup_dir: Path) -> list[Path]:
    """Oldest first."""
    return sorted(backup_dir.glob(f"{PREFIX}*.db")) if backup_dir.is_dir() else []
