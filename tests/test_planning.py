"""The email to planning: default template, admin edits, and safe placeholder filling."""

from fastapi.testclient import TestClient

from app.main import app
from app.services import planning
from tests.conftest import login, make_user
from tests.helpers import admin_client, post_offer, reactions


def _swap(people, **offer):
    """Daan gives a shift away, Sanne takes it. Returns (giver client, taker client)."""
    _, d = people["daan"]
    _, s = people["sanne"]
    listing = post_offer(d, **offer)
    s.post(f"/listings/{listing.id}/react")
    d.post(f"/reactions/{reactions(listing.id)[0].id}/accept")
    return d, s


def test_default_mail(people):
    _, s = _swap(people, code="HG", start="19:10", end="22:30")
    page = s.get("/mijn").text
    assert "Sanne de Vries neemt de volgende dienst over van Daan Bakker" in page
    assert "Soort:    HG" in page and "Tijd:     19:10–22:30" in page
    assert "Zaal:" not in page  # only what was filled in
    assert "Aan: planning@voorbeeld.nl" in page
    assert "mailto:planning%40voorbeeld.nl" in page


def test_admin_edits_and_resets_the_template(people):
    _, a = admin_client()
    a.post(
        "/beheer/mail",
        data={
            "subject": "Ruil {datum_iso} {soort}",
            "body": "Hoi!\n{nemer} doet {soort} voor {gever}. {onbekend}",
        },
    )
    _, s = _swap(people, code="H")
    page = s.get("/mijn").text
    assert "Onderwerp: Ruil " in page and "Sanne de Vries doet H voor Daan Bakker" in page
    assert "{onbekend}" in page  # unknown placeholders stay as typed
    a.post("/beheer/mail", data={"reset": "1"})
    assert "neemt de volgende dienst over van" in s.get("/mijn").text


def test_template_cannot_reach_attributes():
    values = {"gever": "Daan"}
    assert planning.fill("{gever.__class__} {gever}", values) == "{gever.__class__} Daan"


def test_only_admins_edit_the_template(people):
    _, s = people["sanne"]
    assert s.post("/beheer/mail", data={"subject": "x", "body": "y"}).status_code == 403
    member = make_user("Lid Lid")
    assert login(TestClient(app), member).get("/beheer").status_code == 403
