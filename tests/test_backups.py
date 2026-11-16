import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from app import cli
from app.config import get_settings
from app.services import backups
from tests.conftest import make_user


def test_sqlite_path_only_for_files():
    assert str(backups.sqlite_path("sqlite:////data/ruilingen.db")) == "/data/ruilingen.db"
    assert str(backups.sqlite_path("sqlite:///./ruilingen.db")) == "ruilingen.db"
    assert backups.sqlite_path("sqlite:///:memory:") is None
    assert backups.sqlite_path("postgresql://x/y") is None


def test_snapshot_is_a_readable_copy_and_keeps_the_newest(tmp_path):
    make_user("Anna Voorbeeld")
    db_file = backups.sqlite_path(get_settings().database_url)
    start = datetime(2026, 11, 20, 8, 0)
    for hour in range(5):
        backups.snapshot(db_file, tmp_path, keep=3, now=start + timedelta(hours=hour))

    kept = backups.list_snapshots(tmp_path)
    assert [p.name for p in kept] == [
        "ruilingen-20261120-100000.db",
        "ruilingen-20261120-110000.db",
        "ruilingen-20261120-120000.db",
    ]
    assert not list(tmp_path.glob("*.partial"))
    with sqlite3.connect(kept[-1]) as conn:
        names = [r[0] for r in conn.execute("select name from users")]
    assert names == ["Anna Voorbeeld"]


def test_backup_command(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(get_settings(), "backup_dir", str(tmp_path))
    assert cli.main(["backup"]) == 0
    assert cli.main(["backups"]) == 0
    out = capsys.readouterr().out
    assert out.count("ruilingen-") == 2  # the path printed by backup + the listed copy
    assert len(backups.list_snapshots(tmp_path)) == 1


def test_copy_before_migration_only_when_the_schema_changes(tmp_path):
    root = Path(__file__).parent.parent
    now = datetime(2026, 11, 20, 8, 0)
    db_file = tmp_path / "r.db"
    out = tmp_path / "backups"
    assert "geen database" in backups.before_migration(db_file, out, 48, now, root)

    db_file.touch()  # an empty database: every migration is pending
    assert "kopie voor migratie" in backups.before_migration(db_file, out, 48, now, root)
    assert len(backups.list_snapshots(out)) == 1
    # restarting right after doesn't add copies
    assert "recente kopie" in backups.before_migration(db_file, out, 48, now, root)

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=root,
        env={"DATABASE_URL": f"sqlite:///{db_file}", "PATH": ""},
        check=True,
        capture_output=True,
    )
    assert "geen migratie" in backups.before_migration(db_file, out, 48, now, root)
