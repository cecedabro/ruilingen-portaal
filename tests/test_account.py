"""Your own account, notifications and data retention."""

from datetime import timedelta

from app import mail
from app.config import get_settings
from app.db import SessionLocal
from app.models import (
    Kind,
    Listing,
    User,
)
from app.services import housekeeping
from tests.helpers import (
    TODAY,
    notifications_for,
    post_offer,
)


def test_notification_mail_respects_setting(people):
    daan, d_client = people["daan"]
    _, n_client = people["noor"]
    d_client.post("/account", data={"name": "Daan Bakker"})  # checkbox unticked → off
    listing = post_offer(d_client)
    mail.outbox.clear()
    n_client.post(f"/listings/{listing.id}/react")
    assert mail.outbox == []
    assert notifications_for(daan)  # still in the app


def test_reading_notifications_marks_them_read(people):
    daan, d_client = people["daan"]
    _, n_client = people["noor"]
    listing = post_offer(d_client)
    n_client.post(f"/listings/{listing.id}/react")
    assert 'class="dot"' in d_client.get("/aangeboden").text
    d_client.get("/meldingen")
    assert 'class="dot"' not in d_client.get("/aangeboden").text


def test_delete_account_removes_data_and_tells_reactors(people):
    daan, d_client = people["daan"]
    noor, n_client = people["noor"]
    listing = post_offer(d_client)
    n_client.post(f"/listings/{listing.id}/react")

    d_client.post("/account/delete", data={"confirm": "nee"})
    with SessionLocal() as s:
        assert s.get(User, daan.id) is not None

    d_client.post("/account/delete", data={"confirm": "verwijder"})
    with SessionLocal() as s:
        assert s.get(User, daan.id) is None
        assert s.get(Listing, listing.id) is None
    assert any("weggehaald" in t for t in notifications_for(noor))
    assert d_client.get("/mijn", follow_redirects=False).status_code == 303


def test_cleanup_removes_old_data(people, db):
    daan, _ = people["daan"]
    old = Listing(
        kind=Kind.OFFER,
        user_id=daan.id,
        date=TODAY - timedelta(days=60),
        start="18:00",
        end="23:00",
        shift_type="G",
    )
    recent = Listing(
        kind=Kind.OFFER,
        user_id=daan.id,
        date=TODAY - timedelta(days=2),
        start="18:00",
        end="23:00",
        shift_type="G",
    )
    db.add_all([old, recent])
    db.commit()
    housekeeping.cleanup(db, get_settings(), TODAY)
    assert db.get(Listing, old.id) is None
    assert db.get(Listing, recent.id) is not None
