"""Migrations must really commit and keep existing rows (SQLite batch mode rebuilds tables)."""

import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def alembic(db: Path, *args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env={"DATABASE_URL": f"sqlite:///{db}", "PATH": ""},
        check=True,
        capture_output=True,
    )


def test_upgrade_from_first_release_keeps_data(tmp_path):
    db = tmp_path / "t.db"
    alembic(db, "upgrade", "d2df602710cd")  # schema of v0.1.0
    con = sqlite3.connect(db)
    con.execute(
        "insert into users(email,name,is_admin,is_active,email_notifications,session_epoch,"
        "created_at) values('x@voorbeeld.nl','Oud Account',0,1,1,0,'2026-10-01')"
    )
    con.execute(
        "insert into listings(kind,user_id,date,start,end,shift_type,note,status,created_at)"
        " values('offer',1,'2026-12-01','18:00','23:00','G','','open','2026-10-01')"
    )
    con.commit()
    con.close()

    alembic(db, "upgrade", "head")

    con = sqlite3.connect(db)
    heads = {p.name.split("_")[0] for p in (ROOT / "migrations/versions").glob("*.py")}
    assert con.execute("select version_num from alembic_version").fetchone()[0] in heads
    assert con.execute("select count(*) from listings").fetchone()[0] == 1
    # email became optional
    con.execute(
        "insert into users(name,is_admin,is_active,email_notifications,session_epoch,created_at)"
        " values('Zonder Mail',0,1,1,0,'2026-10-01')"
    )
