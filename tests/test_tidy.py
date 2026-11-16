"""Old things go away by themselves: started shifts, finished swaps, notifications; plus the
preferences that steer it (Profiel), overnight shifts and the help page."""

from datetime import UTC, datetime, time, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings, get_settings
from app.db import SessionLocal
from app.main import app
from app.models import Notification, User
from app.services import housekeeping
from tests.helpers import TODAY, post_offer, reactions, shown

TOMORROW = TODAY + timedelta(days=1)


def at(monkeypatch, day, hhmm):
    moment = datetime.combine(day, time.fromisoformat(hhmm))
    monkeypatch.setattr(Settings, "now", lambda self: moment)


def deal(people):
    """Daan gives away tomorrow's 18:00–23:00 shift, Sanne takes it."""
    _, d = people["daan"]
    _, s = people["sanne"]
    listing = post_offer(d, day=TOMORROW, start="18:00", end="23:00", note="morgen")
    s.post(f"/listings/{listing.id}/react")
    d.post(f"/reactions/{reactions(listing.id)[0].id}/accept")
    return listing


def test_overnight_shift_is_fine_but_a_day_long_one_is_a_typo(people):
    _, d = people["daan"]
    listing = post_offer(d, start="22:30", end="01:00", note="nacht")
    assert listing.end == "01:00"
    assert listing.info.when == "22:30–01:00 (+1)"
    assert 'class="plus1"' in d.get("/aangeboden").text

    page = d.post(
        "/plaatsen",
        data={
            "kind": "offer",
            "day": TOMORROW.isoformat(),
            "start": "16:12",
            "end": "15:12",
            "code": "H",
        },
    ).text
    assert "De eindtijd ligt vóór de begintijd" in page


def test_a_shift_leaves_the_board_once_it_has_started(people, monkeypatch):
    _, d = people["daan"]
    _, s = people["sanne"]
    post_offer(d, day=TOMORROW, start="18:00", end="23:00", note="morgen")
    at(monkeypatch, TOMORROW, "17:59")
    assert shown(s) == {"morgen"}
    at(monkeypatch, TOMORROW, "18:00")
    assert shown(s) == set()


def test_finished_swap_stays_until_planning_is_mailed_then_follows_preference(people, monkeypatch):
    sanne, s = people["sanne"]
    daan, d = people["daan"]
    listing = deal(people)
    mine = f'id="l{listing.id}"'

    at(monkeypatch, TOMORROW + timedelta(days=1), "09:00")  # the shift is over
    assert mine in s.get("/mijn").text  # planning not mailed yet: stays for both
    assert mine in d.get("/mijn").text

    s.post(f"/listings/{listing.id}/mail-sent")
    assert mine not in s.get("/mijn").text  # default: gone after the shift
    d.post("/account/voorkeuren", data={"keep_deals": "7", "keep_read": "7"})
    assert mine in d.get("/mijn").text  # Daan keeps them a week
    at(monkeypatch, TOMORROW + timedelta(days=8), "09:00")
    assert mine not in d.get("/mijn").text


def test_wissen_clears_a_swap_for_yourself_only(people):
    _, s = people["sanne"]
    _, d = people["daan"]
    listing = deal(people)
    mine = f'id="l{listing.id}"'
    assert mine in s.get("/mijn").text
    s.post(f"/listings/{listing.id}/wissen")
    assert mine not in s.get("/mijn").text
    assert mine in d.get("/mijn").text
    # someone else's swap can't be cleared
    _, n = people["noor"]
    assert "Ruil niet gevonden" in n.post(f"/listings/{listing.id}/wissen").text


def _notifs(user):
    with SessionLocal() as db:
        return list(db.scalars(select(Notification).where(Notification.user_id == user.id)))


def test_clear_one_or_all_notifications(people):
    sanne, s = people["sanne"]
    deal(people)
    deal(people)
    first, *_ = _notifs(sanne)
    assert len(_notifs(sanne)) == 2
    assert "Alles wissen" in s.get("/meldingen").text
    s.post(f"/meldingen/{first.id}/wissen")
    assert len(_notifs(sanne)) == 1
    s.post("/meldingen/wissen")
    assert _notifs(sanne) == []
    assert "Geen meldingen" in s.get("/meldingen").text


def test_notifications_go_after_their_shift_day_and_read_ones_after_preference(people, monkeypatch):
    sanne, s = people["sanne"]
    daan, d = people["daan"]
    deal(people)  # Daan: "Sanne wil je dienst overnemen", Sanne: "… is rond"
    assert {n.about_date for n in _notifs(sanne) + _notifs(daan)} == {TOMORROW}

    at(monkeypatch, TOMORROW + timedelta(days=1), "09:00")
    s.get("/meldingen")
    assert _notifs(sanne) == []

    # housekeeping does the same for everyone, plus read ones after each preference
    with SessionLocal() as db:
        db.add(Notification(user_id=daan.id, text="oud", read_at=datetime(2000, 1, 1, tzinfo=UTC)))
        db.commit()
        housekeeping.cleanup(db, get_settings(), TOMORROW + timedelta(days=1))
    assert _notifs(daan) == []


def test_preferences_and_start_page(people):
    sanne, s = people["sanne"]
    r = s.post(
        "/account/voorkeuren",
        data={"keep_deals": "", "keep_read": "1", "start_page": "mijn", "theme": "dark"},
        follow_redirects=False,
    )
    assert r.status_code == 303 and "theme=dark" in r.headers["set-cookie"]
    with SessionLocal() as db:
        u = db.get(User, sanne.id)
        assert (u.keep_deals_days, u.keep_read_days, u.start_page) == (None, 1, "mijn")
    assert s.get("/", follow_redirects=False).headers["location"] == "/mijn"
    page = s.get("/account").text
    assert "Voorkeuren" in page and "<title>Profiel" in page

    bad = s.post("/account/voorkeuren", data={"keep_deals": "99"}).text
    assert "Kies een van de opties" in bad


def test_help_is_public_and_the_banner_shows_once(people):
    assert "Zo werkt het" in TestClient(app).get("/help").text
    _, s = people["sanne"]
    assert "Nieuw hier?" in s.get("/aangeboden").text
    s.get("/help")
    assert "Nieuw hier?" not in s.get("/aangeboden").text

    _, d = people["daan"]
    d.post("/help/gezien", data={"next": "/mijn"})
    assert "Nieuw hier?" not in d.get("/mijn").text
    assert 'href="/help"' in d.get("/mijn").text  # footer link stays
