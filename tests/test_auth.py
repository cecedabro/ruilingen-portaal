"""Joining, logging in, sessions and request safety."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import mail
from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.models import (
    InviteLink,
    User,
    utcnow,
)
from app.services import invites, logins
from tests.conftest import join, login, make_user
from tests.helpers import (
    admin_client,
    new_link,
)


def test_pages_need_login():
    client = TestClient(app)
    r = client.get("/aangeboden", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")


def test_one_time_link_needs_a_click_and_works_once():
    user = make_user("Lotte Visser")
    with SessionLocal() as db:
        link = logins.make_link(db, get_settings(), db.get(User, user.id))
    path = link.removeprefix("http://testserver")
    client = TestClient(app)
    # A chat/mail link preview opening the link must not log in or burn it.
    assert "Inloggen op dit apparaat" in client.get(path).text
    assert client.get("/aangeboden", follow_redirects=False).status_code == 303
    client.post(path, data={"next": "/gezocht"}, follow_redirects=False)
    assert "Lotte Visser" in client.get("/aangeboden").text
    r = TestClient(app).post(path, follow_redirects=True)
    assert "verlopen of al gebruikt" in r.text


def test_no_email_login():
    client = TestClient(app)
    assert 'name="email"' not in client.get("/login").text
    assert client.post("/login", data={"email": "x@voorbeeld.nl"}).status_code == 405


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


@pytest.mark.parametrize(
    "target", ["//evil.com", "https://evil.com", "/\\evil.com", "javascript:x"]
)
def test_open_redirects_blocked(target):
    from app.web.responses import safe_next

    assert safe_next(target, "/fallback") == "/fallback"


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
        code = invites.main_link(s).code
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
    assert path.startswith("/email/")
    stranger = TestClient(app)
    stranger.post(path)
    assert stranger.get("/aangeboden", follow_redirects=False).status_code == 303  # no login
    with SessionLocal() as s:
        user = s.scalars(select(User).where(User.name == "Milan Jansen")).one()
        assert user.email == "milan@voorbeeld.nl"


def test_member_link_with_use_limit_and_revoke():
    _, a = admin_client()
    path = new_link(a, label="Lichting", role="member", max_uses="2", valid_days="")
    for name in ["Een Lid", "Twee Lid"]:
        assert (
            TestClient(app).post(path, data={"name": name}, follow_redirects=False).status_code
            == 303
        )
    r = TestClient(app).post(path, data={"name": "Drie Lid"})
    assert r.status_code == 422 and "werkt niet meer" in r.text  # full
    path2 = new_link(a, label="Weg", role="member", max_uses="", valid_days="7")
    with SessionLocal() as s:
        link = s.scalars(select(InviteLink).where(InviteLink.label == "Weg")).one()
        assert link.expires_at is not None and link.max_uses is None
    a.post(f"/beheer/links/{link.id}/revoke")
    assert "werkt niet meer" in TestClient(app).get(path2).text


def test_expired_link_does_not_work():
    _, a = admin_client()
    path = new_link(a, label="Kort", role="member", max_uses="", valid_days="1")
    with SessionLocal() as s:
        link = s.scalars(select(InviteLink).where(InviteLink.label == "Kort")).one()
        link.expires_at = utcnow() - timedelta(minutes=1)
        s.commit()
    assert "werkt niet meer" in TestClient(app).get(path).text


def test_admin_link_is_single_use_one_day_and_makes_admin():
    _, a = admin_client()
    path = new_link(a, label="Nieuwe beheerder", role="admin", max_uses="50", valid_days="300")
    with SessionLocal() as s:
        link = s.scalars(select(InviteLink).where(InviteLink.role == "admin")).one()
        assert link.max_uses == 1  # forced, whatever the form said
        assert link.expires_at - utcnow() <= timedelta(hours=24)
    newcomer = TestClient(app)
    assert "Je wordt beheerder" in newcomer.get(path).text
    newcomer.post(path, data={"name": "Nieuwe Baas"})
    assert newcomer.get("/beheer").status_code == 200
    assert "werkt niet meer" in TestClient(app).get(path).text  # used up


def test_renewing_the_group_link():
    _, a = admin_client()
    with SessionLocal() as s:
        old = invites.main_link(s).code
    join(TestClient(app), "Via Groep")  # counts as a use of the main link
    a.post("/beheer/links/main")
    assert "werkt niet meer" in TestClient(app).get(f"/join/{old}").text
    with SessionLocal() as s:
        new = invites.main_link(s)
        assert new.code != old and new.uses == 0
    assert "Hoe heet je" in TestClient(app).get(f"/join/{new.code}").text
