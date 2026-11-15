import sqlite3
from datetime import datetime, timedelta

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
