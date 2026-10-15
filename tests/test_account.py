"""Your own account, notifications and data retention."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import mail
from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.models import (
    Kind,
    Listing,
    LoginToken,
    User,
)
from app.services import housekeeping
from tests.conftest import join
from tests.helpers import (
    TODAY,
    notifications_for,
    post_offer,
    reactions,
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


def test_only_reactions_send_mail(people):
    daan, d_client = people["daan"]
    noor, n_client = people["noor"]
    listing = post_offer(d_client)
    mail.outbox.clear()
    n_client.post(f"/listings/{listing.id}/react")
    assert [m["To"] for m in mail.outbox] == [daan.email]
    assert "wil je HG-dienst" in mail.outbox[0]["Subject"]
    assert f"/mijn#l{listing.id}" in mail.outbox[0].get_content()
    mail.outbox.clear()
    d_client.post(f"/reactions/{reactions(listing.id)[0].id}/accept")
    assert mail.outbox == []  # "you were chosen" is bell-only
    assert any("heeft bevestigd" in t for t in notifications_for(noor))


def _confirm_email(client, address):
    """Add an address and open its confirmation link (as the person would from their mail)."""
    mail.outbox.clear()
    client.post("/account/email", data={"email": address})
    path = mail.outbox[-1].get_content().split("http://testserver")[1].split()[0]
    TestClient(app).post(path)


def _email_of(name):
    with SessionLocal() as s:
        return s.scalars(select(User).where(User.name == name)).one().email


def test_account_shows_address_pending_state_and_remove():
    d = join(TestClient(app), "Daan Bakker")  # joined with just a name: no address yet
    page = d.get("/account").text
    assert "Koppel" in page and "Wijzig adres" not in page  # no address yet

    d.post("/account/email", data={"email": "daan@voorbeeld.nl"})
    page = d.get("/account").text
    assert "Wacht op bevestiging" in page and "daan@voorbeeld.nl" in page
    assert _email_of("Daan Bakker") is None  # not saved before it's confirmed

    _confirm_email(d, "daan@voorbeeld.nl")
    page = d.get("/account").text
    assert "Wacht op bevestiging" not in page
    assert "Wijzig adres" in page and "Verwijder e-mailadres" in page
    assert _email_of("Daan Bakker") == "daan@voorbeeld.nl"


def test_same_address_is_refused_without_sending_mail(people):
    _, d = people["daan"]
    _confirm_email(d, "daan@voorbeeld.nl")
    mail.outbox.clear()
    r = d.post("/account/email", data={"email": "Daan@Voorbeeld.nl "}, follow_redirects=True)
    assert "staat al ingesteld" in r.text
    assert mail.outbox == []


def test_remove_email_deletes_it_and_unconfirmed_attempts(people):
    daan, d = people["daan"]
    _, n = people["noor"]
    _confirm_email(d, "daan@voorbeeld.nl")
    d.post("/account/email", data={"email": "nieuw@voorbeeld.nl"})  # an unconfirmed change
    r = d.post("/account/email/remove", follow_redirects=True)
    assert "e-mailadres is verwijderd" in r.text
    assert _email_of("Daan Bakker") is None
    with SessionLocal() as s:  # no address left anywhere, not even in a pending token
        assert s.scalar(select(func.count(LoginToken.id)).where(LoginToken.email.is_not(None))) == 0

    listing = post_offer(d)
    mail.outbox.clear()
    n.post(f"/listings/{listing.id}/react")
    assert mail.outbox == []  # no address, no mail; the bell still works
    assert notifications_for(daan)
