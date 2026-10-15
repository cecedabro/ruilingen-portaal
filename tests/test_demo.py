"""Demo data: seeded on the live site for the pilot, removable in one go."""

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Listing, User
from app.services import demo
from tests.helpers import TODAY, admin_client, notifications_for


def _count(model):
    with SessionLocal() as s:
        return s.scalar(select(func.count(model.id)))


def test_seed_is_once_and_remove_only_touches_demo(people):
    sanne, s_client = people["sanne"]  # a real colleague (also named in the demo list)
    with SessionLocal() as s:
        created = demo.seed(s, TODAY)
        assert demo.seed(s, TODAY) == 0  # never twice
    assert created == len(demo.NAMES) - 3  # Sanne, Daan and Noor already exist
    assert _count(Listing) >= 20
    page = s_client.get("/aangeboden").text
    assert "Overnemen" in page and "reactie" in page

    # a real colleague reacts to a demo shift, then the demo data is removed
    with SessionLocal() as s:
        lid = s.scalars(
            select(Listing.id).where(Listing.kind == "offer", Listing.mode == "give")
        ).first()
    s_client.post(f"/listings/{lid}/react")
    _, a = admin_client()
    assert "Demo-data verwijderen" in a.get("/beheer").text
    a.post("/beheer/demo/remove")
    assert _count(Listing) == 0
    with SessionLocal() as s:
        names = set(s.scalars(select(User.name)))
    assert {"Sanne de Vries", "Daan Bakker", "Noor Smit", "Ad Min"} == names  # real ones stay
    assert any("weggehaald" in t for t in notifications_for(sanne))
    assert "Demo-data verwijderen" not in a.get("/beheer").text
