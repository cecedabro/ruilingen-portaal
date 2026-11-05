"""Beheer: members, lists, removing listings."""

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import (
    Listing,
    ListingStatus,
    User,
)
from tests.conftest import login, make_user
from tests.helpers import (
    admin_client,
    notifications_for,
    post_offer,
)


def test_members_cannot_use_beheer(people):
    _, s_client = people["sanne"]
    assert s_client.get("/beheer").status_code == 403
    assert s_client.post("/beheer/links", data={"role": "admin"}).status_code == 403


def test_admin_promotes_and_deletes_members(people):
    sanne, s_client = people["sanne"]
    daan, d_client = people["daan"]
    noor, n_client = people["noor"]
    admin, a = admin_client()
    a.post(f"/beheer/users/{sanne.id}/admin")
    assert s_client.get("/beheer").status_code == 200
    a.post(f"/beheer/users/{sanne.id}/admin")
    assert s_client.get("/beheer").status_code == 403

    listing = post_offer(d_client)
    n_client.post(f"/listings/{listing.id}/react")
    a.post(f"/beheer/users/{daan.id}/delete")
    with SessionLocal() as s:
        assert s.get(User, daan.id) is None and s.get(Listing, listing.id) is None
    assert any("weggehaald" in t for t in notifications_for(noor))
    assert d_client.get("/mijn", follow_redirects=False).status_code == 303

    # an admin can't delete themselves here, and the last admin can't be demoted or deleted
    a.post(f"/beheer/users/{admin.id}/delete")
    a.post(f"/beheer/users/{admin.id}/admin")
    with SessionLocal() as s:
        assert s.get(User, admin.id).is_admin
    r = a.post("/account/delete", data={"confirm": "verwijder"}, follow_redirects=True)
    assert "enige beheerder" in r.text


def test_admin_removes_someones_shift(people):
    daan, d_client = people["daan"]
    noor, n_client = people["noor"]
    _, a = admin_client()
    listing = post_offer(d_client)
    n_client.post(f"/listings/{listing.id}/react")
    assert "Verwijderen (beheer)" in a.get("/aangeboden").text
    assert "Verwijderen (beheer)" not in n_client.get("/aangeboden").text
    a.post(f"/beheer/listings/{listing.id}/delete")
    with SessionLocal() as s:
        assert s.get(Listing, listing.id).status == ListingStatus.REMOVED
    assert any("beheerder heeft je dienst" in t for t in notifications_for(daan))
    assert any("weggehaald" in t for t in notifications_for(noor))
    assert n_client.post(f"/beheer/listings/{listing.id}/delete").status_code == 403


def test_admin_edits_venue_lists(people):
    _, s_client = people["sanne"]
    admin = make_user("Ad Min", is_admin=True)
    a_client = login(TestClient(app), admin)
    a_client.post("/beheer/lijsten", data={"halls": "Zaal A\nZaal B\n\nOverig"})
    a_client.post(
        "/beheer/werkplekken",
        data={
            "hall_name": ["Zaal A", "Zaal B"],
            "hall_places": ["Bar 1\nFoyer", "Foyer\nBar 2"],
            "everywhere": "Overig",
        },
    )
    page = s_client.get("/plaatsen").text
    assert ">Zaal A</option>" in page and ">Bar 1</option>" in page
    assert ">Grote Zaal</option>" not in page
    assert s_client.post("/beheer/lijsten", data={"halls": "x"}).status_code == 403


def test_werkplekken_per_zaal_survive_saving_again():
    from app.db import SessionLocal
    from app.services import appdata

    admin = make_user("Ad Min", is_admin=True)
    a = login(TestClient(app), admin)
    a.post("/beheer/lijsten", data={"halls": "Grote Zaal\nKleine Zaal"})
    a.post(
        "/beheer/werkplekken",
        data={
            "hall_name": ["Grote Zaal", "Kleine Zaal", "Onbekend"],
            "hall_places": ["Bach\nBordes", "Felix\nBordes", "Spook"],
            "everywhere": "Overig",
        },
    )
    with SessionLocal() as db:
        assert appdata.get_value(db, "workplaces") == (
            "Bach | Grote Zaal\nBordes | Grote Zaal, Kleine Zaal\nFelix | Kleine Zaal\nOverig"
        )
        by_hall, everywhere = appdata.workplaces_by_hall(db)
    assert by_hall == {"Grote Zaal": ["Bach", "Bordes"], "Kleine Zaal": ["Bordes", "Felix"]}
    assert everywhere == ["Overig"]

    # the page shows the saved mapping, so saving the page again changes nothing
    page = a.get("/beheer").text
    assert "Bach\nBordes</textarea>" in page and "Felix\nBordes" not in page
    assert "Bordes\nFelix</textarea>" in page
