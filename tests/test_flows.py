import threading
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import mail, services
from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.models import Kind, Listing, ListingStatus, Notification, Reaction, ReactionStatus, User
from tests.conftest import join, login, make_user

TODAY = services.local_today(get_settings())


def post_offer(client, day=None, code="HG", start="18:00", end="23:30", note=""):
    day = day or TODAY + timedelta(days=3)
    r = client.post(
        "/plaatsen",
        data={
            "kind": "offer",
            "day": day.isoformat(),
            "start": start,
            "end": end,
            "code": code,
            "note": note,
        },
    )
    assert r.status_code == 200, r.text
    with SessionLocal() as s:
        return s.scalars(select(Listing).order_by(Listing.id.desc())).first()


def reactions(listing_id):
    with SessionLocal() as s:
        return list(
            s.scalars(
                select(Reaction).where(Reaction.listing_id == listing_id).order_by(Reaction.id)
            )
        )


def notifications_for(user):
    with SessionLocal() as s:
        return [
            n.text for n in s.scalars(select(Notification).where(Notification.user_id == user.id))
        ]


# ---------------------------------------------------------------- login


def test_pages_need_login():
    client = TestClient(app)
    r = client.get("/aangeboden", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")


def test_unknown_address_gets_no_mail_and_same_message():
    client = TestClient(app)
    r = client.post("/login", data={"email": "stranger@voorbeeld.nl"})
    assert "Check je mail" in r.text
    assert mail.outbox == []


def test_magic_link_needs_a_click_and_works_once():
    user = make_user("Lotte Visser")
    client = TestClient(app)
    client.post("/login", data={"email": "  Lotte.Visser@Voorbeeld.nl "})
    body = mail.outbox[-1].get_content()
    path = body.split("http://testserver")[1].split()[0]

    # A mail scanner opening the link must not log in or burn the token.
    assert "Inloggen" in client.get(path).text
    assert client.get("/aangeboden", follow_redirects=False).status_code == 303

    client.post(path, data={"next": "/gezocht"}, follow_redirects=False)
    assert client.get("/aangeboden").status_code == 200
    assert user.name in client.get("/aangeboden").text

    other = TestClient(app)
    r = other.post(path, follow_redirects=True)
    assert "verlopen of al gebruikt" in r.text


def test_login_mails_are_rate_limited():
    make_user("Bram Meijer")
    client = TestClient(app)
    for _ in range(8):
        client.post("/login", data={"email": "bram.meijer@voorbeeld.nl"})
    assert len(mail.outbox) == get_settings().login_mails_per_hour


def test_blocked_user_is_logged_out(people):
    sanne, client = people["sanne"]
    with SessionLocal() as s:
        s.get(User, sanne.id).is_active = False
        s.commit()
    assert client.get("/aangeboden", follow_redirects=False).status_code == 303


def test_logout_everywhere(people):
    sanne, client = people["sanne"]
    second_device = login(TestClient(app), sanne)
    client.post("/account/logout-everywhere")
    assert second_device.get("/mijn", follow_redirects=False).status_code == 303


def test_cross_site_post_is_refused(people):
    _, client = people["sanne"]
    r = client.post("/plaatsen", data={"kind": "offer"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = client.post("/plaatsen", data={"kind": "offer"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


# ---------------------------------------------------------------- offered shifts


def test_offer_flow_first_come_order_and_confirm(people):
    sanne, s_client = people["sanne"]
    daan, d_client = people["daan"]
    noor, n_client = people["noor"]

    listing = post_offer(d_client, note="Verjaardag")
    assert "Verjaardag" in s_client.get("/aangeboden").text

    n_client.post(f"/listings/{listing.id}/react")  # Noor first
    s_client.post(f"/listings/{listing.id}/react")  # Sanne second
    rs = reactions(listing.id)
    assert [r.user_id for r in rs] == [noor.id, sanne.id]
    assert any("wil je HG-dienst" in t for t in notifications_for(daan))

    # Daan sees both in order, and picks the second one: not limited to the first.
    page = d_client.get("/mijn").text
    assert page.index("Noor Smit") < page.index("Sanne de Vries")
    r = d_client.post(f"/reactions/{rs[1].id}/accept", follow_redirects=True)
    assert "Rond!" in r.text

    rs = reactions(listing.id)
    assert rs[0].status == ReactionStatus.EXPIRED
    assert rs[1].status == ReactionStatus.ACCEPTED
    assert any("aan iemand anders gegeven" in t for t in notifications_for(noor))
    assert any("heeft bevestigd" in t for t in notifications_for(sanne))

    # The planning mail: taker takes over from giver, both in Cc.
    page = s_client.get("/mijn").text
    assert "Sanne de Vries neemt de volgende dienst over van Daan Bakker" in page
    assert "planning@voorbeeld.nl" in page
    assert (
        "sanne.de.vries@voorbeeld.nl, daan.bakker@voorbeeld.nl" in page.replace("&#64;", "@")
        or "daan.bakker@voorbeeld.nl" in page
    )

    # Listing is gone from the board and can't be accepted twice.
    assert f'id="l{listing.id}"' not in n_client.get("/aangeboden").text
    r = d_client.post(f"/reactions/{rs[0].id}/accept", follow_redirects=True)
    assert "afgehandeld" in r.text or "vergeven" in r.text


def test_cannot_react_to_own_or_twice(people):
    _, d_client = people["daan"]
    noor, n_client = people["noor"]
    listing = post_offer(d_client)

    r = d_client.post(f"/listings/{listing.id}/react", follow_redirects=True)
    assert "eigen dienst" in r.text

    n_client.post(f"/listings/{listing.id}/react")
    r = n_client.post(f"/listings/{listing.id}/react", follow_redirects=True)
    assert "al op gereageerd" in r.text
    assert len(reactions(listing.id)) == 1


def test_withdraw_then_react_again(people):
    _, d_client = people["daan"]
    _, n_client = people["noor"]
    listing = post_offer(d_client)
    n_client.post(f"/listings/{listing.id}/react")
    first = reactions(listing.id)[0]
    n_client.post(f"/reactions/{first.id}/withdraw")
    assert reactions(listing.id)[0].status == ReactionStatus.WITHDRAWN
    n_client.post(f"/listings/{listing.id}/react")
    assert [r.status for r in reactions(listing.id)] == [
        ReactionStatus.WITHDRAWN,
        ReactionStatus.PENDING,
    ]


def test_cannot_accept_withdrawn_reaction(people):
    _, d_client = people["daan"]
    _, n_client = people["noor"]
    listing = post_offer(d_client)
    n_client.post(f"/listings/{listing.id}/react")
    r = reactions(listing.id)[0]
    n_client.post(f"/reactions/{r.id}/withdraw")
    page = d_client.post(f"/reactions/{r.id}/accept", follow_redirects=True).text
    assert "ingetrokken of al afgehandeld" in page
    with SessionLocal() as s:
        assert s.get(Listing, listing.id).status == ListingStatus.OPEN


def test_only_owner_can_accept_or_decline(people):
    _, d_client = people["daan"]
    _, n_client = people["noor"]
    _, s_client = people["sanne"]
    listing = post_offer(d_client)
    n_client.post(f"/listings/{listing.id}/react")
    r = reactions(listing.id)[0]
    assert "niet gevonden" in s_client.post(f"/reactions/{r.id}/accept", follow_redirects=True).text
    assert (
        "niet gevonden" in s_client.post(f"/reactions/{r.id}/decline", follow_redirects=True).text
    )


def test_decline_notifies(people):
    _, d_client = people["daan"]
    noor, n_client = people["noor"]
    listing = post_offer(d_client)
    n_client.post(f"/listings/{listing.id}/react")
    d_client.post(f"/reactions/{reactions(listing.id)[0].id}/decline")
    assert reactions(listing.id)[0].status == ReactionStatus.DECLINED
    assert any("afgewezen" in t for t in notifications_for(noor))


def test_remove_listing_expires_reactions(people):
    _, d_client = people["daan"]
    noor, n_client = people["noor"]
    listing = post_offer(d_client)
    n_client.post(f"/listings/{listing.id}/react")
    d_client.post(f"/listings/{listing.id}/remove")
    assert reactions(listing.id)[0].status == ReactionStatus.EXPIRED
    assert any("weggehaald" in t for t in notifications_for(noor))
    assert "niet meer" in n_client.post(f"/listings/{listing.id}/react", follow_redirects=True).text


def test_validation_errors_keep_form(people):
    _, client = people["daan"]
    r = client.post(
        "/plaatsen",
        data={
            "kind": "offer",
            "day": (TODAY - timedelta(days=1)).isoformat(),
            "start": "18:00",
            "end": "23:00",
            "code": "HG",
            "note": "bewaar mij",
        },
    )
    assert r.status_code == 422 and "al voorbij" in r.text and "bewaar mij" in r.text
    r = client.post(
        "/plaatsen",
        data={
            "kind": "offer",
            "day": TODAY.isoformat(),
            "start": "18:00",
            "end": "23:00",
            "code": "XYZ",
        },
    )
    assert r.status_code == 422 and "soort dienst" in r.text
    r = client.post("/plaatsen", data={"kind": "wanted", "day": TODAY.isoformat()})
    assert r.status_code == 422 and "minstens één" in r.text


def test_past_listings_are_hidden(people, db):
    daan, d_client = people["daan"]
    db.add(
        Listing(
            kind=Kind.OFFER,
            user_id=daan.id,
            date=TODAY - timedelta(days=1),
            start="18:00",
            end="23:00",
            shift_type="G",
            note="gisteren-dienst",
        )
    )
    db.commit()
    _, s_client = people["sanne"]
    assert "gisteren-dienst" not in s_client.get("/aangeboden").text
    assert "gisteren-dienst" not in d_client.get("/mijn").text


# ---------------------------------------------------------------- wanted shifts


def test_wanted_flow_offerer_becomes_giver(people):
    noor, n_client = people["noor"]
    sanne, s_client = people["sanne"]
    day = TODAY + timedelta(days=4)
    n_client.post(
        "/plaatsen", data={"kind": "wanted", "day": day.isoformat(), "codes": ["H", "HG"]}
    )
    with SessionLocal() as s:
        listing = s.scalars(select(Listing).where(Listing.kind == Kind.WANTED)).one()
    assert listing.wanted_type_list == ["H", "HG"]

    r = s_client.post(
        f"/listings/{listing.id}/react",
        data={"offer_type": "G", "offer_start": "19:00"},
        follow_redirects=True,
    )
    assert "begin- als eindtijd" in r.text
    s_client.post(
        f"/listings/{listing.id}/react",
        data={"offer_start": "19:00", "offer_end": "23:00", "offer_type": "G"},
    )
    assert any("biedt je een G-dienst" in t for t in notifications_for(noor))

    n_client.post(f"/reactions/{reactions(listing.id)[0].id}/accept")
    page = n_client.get("/mijn").text
    assert "Noor Smit neemt de volgende dienst over van Sanne de Vries" in page
    assert "19:00–23:00" in page

    # Either party can mark the mail as sent; the other is told.
    s_client.post(f"/listings/{listing.id}/mail-sent")
    assert any("naar planning gemaild" in t for t in notifications_for(noor))
    assert "Planning gemaild door Sanne de Vries" in n_client.get("/mijn").text


# ---------------------------------------------------------------- concurrency


def test_simultaneous_accepts_give_the_shift_away_once(people):
    daan, d_client = people["daan"]
    _, n_client = people["noor"]
    _, s_client = people["sanne"]
    listing = post_offer(d_client)
    n_client.post(f"/listings/{listing.id}/react")
    s_client.post(f"/listings/{listing.id}/react")
    ids = [r.id for r in reactions(listing.id)]

    barrier = threading.Barrier(2)
    results = []

    def go(rid):
        with SessionLocal() as s:
            user = s.get(User, daan.id)
            barrier.wait()
            try:
                services.run_write(s, services.accept, user, rid, today=TODAY)
                results.append("ok")
            except services.SwapError as e:
                results.append(str(e))

    threads = [threading.Thread(target=go, args=(rid,)) for rid in ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count("ok") == 1, results
    statuses = sorted(r.status for r in reactions(listing.id))
    assert statuses == [ReactionStatus.ACCEPTED, ReactionStatus.EXPIRED]


# ---------------------------------------------------------------- account, admin, housekeeping


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


def test_admin_pages(people):
    sanne, s_client = people["sanne"]
    assert s_client.get("/beheer").status_code == 403

    admin = make_user("Ad Min", is_admin=True)
    a_client = login(TestClient(app), admin)
    page = a_client.get("/beheer").text
    old_code = page.split("/join/")[1].split('"')[0]

    # A one-time link for a colleague who lost their phone.
    page = a_client.post(f"/beheer/users/{sanne.id}/link").text
    link = page.split('id="userlink" value="http://testserver')[1].split('"')[0]
    phone = TestClient(app)
    phone.post(link, follow_redirects=False)
    assert "Sanne de Vries" in phone.get("/aangeboden").text

    # Rotating the join link stops the old one.
    a_client.post("/beheer/join-link")
    assert "werkt niet meer" in TestClient(app).get(f"/join/{old_code}").text


def test_admin_bootstrap_on_startup():
    with TestClient(app):  # runs lifespan
        pass
    with SessionLocal() as s:
        admin = s.scalars(select(User).where(User.email == "admin@voorbeeld.nl")).one()
        assert admin.is_admin


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
    services.cleanup(db, get_settings(), TODAY)
    assert db.get(Listing, old.id) is None
    assert db.get(Listing, recent.id) is not None


@pytest.mark.parametrize(
    "target", ["//evil.com", "https://evil.com", "/\\evil.com", "javascript:x"]
)
def test_open_redirects_blocked(target):
    from app.web import safe_next

    assert safe_next(target, "/fallback") == "/fallback"


def test_planning_mail_template():
    from app.shifts import ShiftInfo, planning_mail

    full = ShiftInfo("HG", date(2026, 10, 17), "18:00", "23:30", None, "Grote Zaal", "Foyer 2")
    m = planning_mail(
        planning="p@x.nl",
        giver_name="A Een",
        giver_email="a@x.nl",
        taker_name="B Twee",
        taker_email="b@x.nl",
        shift=full,
    )
    assert m.subject == "Dienstruil za 17 okt · HG 18:00–23:30"
    assert "B Twee neemt de volgende dienst over van A Een" in m.body
    assert "zaterdag 17 oktober (2026-10-17)" in m.body
    assert "Soort:    HG" in m.body and "Zaal:     Grote Zaal" in m.body
    assert "Werkplek: Foyer 2" in m.body
    assert m.cc == ["a@x.nl", "b@x.nl"]
    assert m.mailto.startswith("mailto:p%40x.nl?cc=")

    # Only what was filled in: "HG, saturday evening".
    bare = ShiftInfo("HG", date(2026, 10, 17), daypart="avond")
    m = planning_mail(
        planning="p@x.nl",
        giver_name="A",
        giver_email=None,
        taker_name="B",
        taker_email=None,
        shift=bare,
    )
    assert m.subject == "Dienstruil za 17 okt · HG avond"
    assert "Tijd:     avond" in m.body
    assert "Zaal" not in m.body and "Werkplek" not in m.body


# ---------------------------------------------------------------- join link (no email)


def test_join_with_just_a_name():
    client = join(TestClient(app), "  Fleur   Mulder ")
    page = client.get("/aangeboden").text
    assert "Fleur Mulder" in page
    with SessionLocal() as s:
        user = s.scalars(select(User).where(User.name == "Fleur Mulder")).one()
        assert user.email is None


def test_join_rejects_bad_code_and_taken_name():
    client = TestClient(app)
    assert "werkt niet meer" in client.get("/join/wrong").text
    r = client.post("/join/wrong", data={"name": "X Y"})
    assert r.status_code == 422 and "werkt niet meer" in r.text
    join(TestClient(app), "Thijs de Boer")
    with SessionLocal() as s:
        from app import auth

        code = auth.join_code(s)
    r = client.post(f"/join/{code}", data={"name": "thijs de boer"})
    assert r.status_code == 422 and "al in gebruik" in r.text


def test_device_link_logs_in_second_device():
    laptop = join(TestClient(app), "Lotte Visser")
    page = laptop.post("/account/device-link").text
    link = page.split('id="devlink" value="http://testserver')[1].split('"')[0]
    phone = TestClient(app)
    assert "Inloggen op dit apparaat" in phone.get(link).text
    phone.post(link, follow_redirects=False)
    assert "Lotte Visser" in phone.get("/mijn").text
    assert "werkt niet meer" in TestClient(app).get(link).text  # single use


def test_add_email_needs_verification():
    client = join(TestClient(app), "Milan Jansen")
    client.post("/account/email", data={"email": "milan@voorbeeld.nl"})
    with SessionLocal() as s:
        assert s.scalars(select(User).where(User.name == "Milan Jansen")).one().email is None
    body = mail.outbox[-1].get_content()
    assert mail.outbox[-1]["To"] == "milan@voorbeeld.nl"
    path = body.split("http://testserver")[1].split()[0]
    client.post(path, follow_redirects=False)
    with SessionLocal() as s:
        user = s.scalars(select(User).where(User.name == "Milan Jansen")).one()
        assert user.email == "milan@voorbeeld.nl"


def test_swap_between_people_without_email():
    giver = join(TestClient(app), "Noor Smit")
    taker = join(TestClient(app), "Bram Meijer")
    listing = post_offer(giver)
    taker.post(f"/listings/{listing.id}/react")
    giver.post(f"/reactions/{reactions(listing.id)[0].id}/accept")
    page = taker.get("/mijn").text
    assert "Bram Meijer neemt de volgende dienst over van Noor Smit" in page
    assert "Cc:" not in page
    assert mail.outbox == []  # nobody has an address, so no notification mails


def test_mail_disabled_hides_email_login(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "dev_mode", False)
    assert not settings.mail_enabled
    assert 'name="email"' not in TestClient(app).get("/login").text


# ---------------------------------------------------------------- optional shift details


def test_offer_with_only_type_and_date(people):
    _, client = people["daan"]
    day = TODAY + timedelta(days=3)
    r = client.post("/plaatsen", data={"kind": "offer", "day": day.isoformat(), "code": "HG"})
    assert r.status_code == 200, r.text
    with SessionLocal() as s:
        listing = s.scalars(select(Listing)).one()
        assert (listing.start, listing.end, listing.daypart, listing.hall) == (None,) * 4


def test_offer_with_all_details(people):
    _, client = people["daan"]
    day = (TODAY + timedelta(days=3)).isoformat()
    client.post(
        "/plaatsen",
        data={
            "kind": "offer",
            "day": day,
            "code": "H",
            "start": "19:10",
            "end": "22:30",
            "daypart": "avond",
            "hall": " Grote  Zaal ",
            "workplace": "Foyer 2",
            "note": "BHV",
        },
    )
    with SessionLocal() as s:
        listing = s.scalars(select(Listing)).one()
        assert listing.info.when == "19:10–22:30"  # a time wins over the part of day
        assert listing.daypart is None
        assert listing.info.where == "Grote Zaal · Foyer 2"
    _, other = people["sanne"]
    page = other.get("/aangeboden").text
    assert "<dd>Grote Zaal</dd>" in page and "<dd>Foyer 2</dd>" in page and "19:10" in page
    # ...and the zaal is suggested next time
    assert '<option value="Grote Zaal">' in client.get("/plaatsen").text


def test_half_a_time_is_rejected(people):
    _, client = people["daan"]
    day = (TODAY + timedelta(days=3)).isoformat()
    r = client.post("/plaatsen", data={"kind": "offer", "day": day, "code": "H", "start": "19:00"})
    assert r.status_code == 422 and "begin- als eindtijd" in r.text


def test_wanted_reply_with_only_a_type(people):
    noor, n_client = people["noor"]
    _, s_client = people["sanne"]
    day = (TODAY + timedelta(days=4)).isoformat()
    n_client.post(
        "/plaatsen", data={"kind": "wanted", "day": day, "codes": ["H"], "daypart": "avond"}
    )
    with SessionLocal() as s:
        listing = s.scalars(select(Listing)).one()
        assert listing.daypart == "avond"
    s_client.post(
        f"/listings/{listing.id}/react", data={"offer_type": "HG", "offer_daypart": "avond"}
    )
    r = reactions(listing.id)[0]
    assert (r.offer_type, r.offer_daypart, r.offer_start) == ("HG", "avond", None)


# ---------------------------------------------------------------- board filters and status


def _offer(client, days, code, **extra):
    data = {"kind": "offer", "day": (TODAY + timedelta(days=days)).isoformat(), "code": code}
    data.update(extra)
    assert client.post("/plaatsen", data=data).status_code == 200


def _shown(client, query=""):
    page = client.get("/aangeboden" + query).text
    with SessionLocal() as s:
        return {lst.note for lst in s.scalars(select(Listing)) if f'id="l{lst.id}"' in page}


def test_board_filters(people):
    _, d = people["daan"]
    _, n = people["noor"]
    _offer(d, 2, "HG", start="19:00", end="23:00", hall="Grote Zaal", note="a")
    _offer(d, 2, "G", daypart="ochtend", hall="Kleine Zaal", note="b")
    _offer(d, 9, "R", note="c")
    _, s_client = people["sanne"]
    assert _shown(s_client) == {"a", "b", "c"}
    assert _shown(s_client, "?soort=G") == {"a", "b"}  # a letter matches HG too
    assert _shown(s_client, "?dagdeel=avond") == {"a"}  # from the start time
    assert _shown(s_client, "?dagdeel=ochtend") == {"b"}
    assert _shown(s_client, "?zaal=grote zaal") == {"a"}
    # someone reacts to "a": it's no longer "vrij"
    with SessionLocal() as s:
        a_id = s.scalars(select(Listing.id).where(Listing.note == "a")).one()
    n.post(f"/listings/{a_id}/react")
    assert _shown(s_client, "?vrij=vrij") == {"b", "c"}
    assert _shown(s_client, "?vrij=bezet") == {"a"}
    assert _shown(s_client, "?soort=X&dagdeel=nacht") == {"a", "b", "c"}  # junk is ignored


def test_posting_order_is_visible(people):
    _, d = people["daan"]
    _, n = people["noor"]
    _offer(d, 9, "H", note="first-posted")
    _offer(n, 2, "G", note="second-posted")
    _, s_client = people["sanne"]
    page = s_client.get("/aangeboden").text
    # by date: the later shift comes last, but still carries #1
    assert page.index("second-posted") < page.index("first-posted")
    assert page.index("#2") < page.index("#1")
    page = s_client.get("/aangeboden?volgorde=geplaatst").text
    assert page.index("first-posted") < page.index("second-posted")
    # filtering doesn't renumber
    assert "#2" in s_client.get("/aangeboden?soort=G").text


def test_board_is_ordered_by_shift_date_and_time(people):
    _, d = people["daan"]
    _offer(d, 5, "H", note="later")
    _offer(d, 2, "H", daypart="avond", note="avond")
    _offer(d, 2, "H", start="10:00", end="14:00", note="ochtend")
    _, s_client = people["sanne"]
    page = s_client.get("/aangeboden").text
    assert page.index("ochtend</dd>") < page.index("avond</dd>") < page.index("later</dd>")


def test_pending_status_is_visible_to_others(people):
    _, d = people["daan"]
    _, n = people["noor"]
    _, s_client = people["sanne"]
    _offer(d, 3, "H")
    with SessionLocal() as s:
        lid = s.scalars(select(Listing.id)).one()
    assert "Overnemen" in s_client.get("/aangeboden").text
    n.post(f"/listings/{lid}/react")
    page = s_client.get("/aangeboden").text
    assert "1 reactie · wacht op Daan" in page and "Reageer als 2e" in page
    assert "je bent de eerste" in n.get("/aangeboden").text
    s_client.post(f"/listings/{lid}/react")
    assert "je bent 2e" in s_client.get("/aangeboden").text
