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
    con.execute(
        "insert into listings(kind,user_id,date,start,end,shift_type,note,status,created_at)"
        " values('offer',1,'2026-12-02','18:00','23:00','I','','open','2026-10-01')"
    )
    con.execute(
        "insert into listings(kind,user_id,date,wanted_types,note,status,created_at)"
        " values('wanted',1,'2026-12-03','H,I,G','','open','2026-10-01')"
    )
    con.commit()
    con.close()

    alembic(db, "upgrade", "7308e71681ff")  # 0.2.0: the group link code lived in app_settings
    con = sqlite3.connect(db)
    con.execute("insert into app_settings(key, value) values('join_code', 'groep-code-123')")
    con.commit()
    con.close()

    alembic(db, "upgrade", "7e500a3621ae")  # 0.8.0: before swaps
    con = sqlite3.connect(db)
    # a reply to the wanted request (listing 3) that offers a shift, written before swaps existed
    con.execute(
        "insert into reactions(listing_id,user_id,status,offer_type,offer_start,offer_end,"
        "created_at) values(3,1,'pending','H','19:00','23:00','2026-10-02')"
    )
    con.commit()
    con.close()

    alembic(db, "upgrade", "head")

    con = sqlite3.connect(db)
    heads = {p.name.split("_")[0] for p in (ROOT / "migrations/versions").glob("*.py")}
    assert con.execute("select version_num from alembic_version").fetchone()[0] in heads
    assert con.execute("select count(*) from listings").fetchone()[0] == 3
    # "I" became "Inwerk", also inside wanted_types
    types = [r[0] for r in con.execute("select coalesce(shift_type, wanted_types) from listings")]
    assert types == ["G", "Inwerk", "H,Inwerk,G"]
    # email became optional
    con.execute(
        "insert into users(name,is_admin,is_active,email_notifications,session_epoch,created_at)"
        " values('Zonder Mail',0,1,1,0,'2026-10-01')"
    )
    # the existing group-chat link keeps working as the main invite link
    row = con.execute("select code, is_main, role from invite_links").fetchall()
    assert row == [("groep-code-123", 1, "member")]
    assert con.execute("select count(*) from app_settings where key='join_code'").fetchone()[0] == 0
    # swaps: existing listings stay "give", and the earlier reply got its date (the request's)
    assert {r[0] for r in con.execute("select mode from listings")} == {"give"}
    assert con.execute("select offer_date from reactions").fetchone() == ("2026-12-03",)
