"""Shared test helpers: post shifts, inspect reactions and notifications, admin clients."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.models import Listing, Notification, Reaction
from tests.conftest import login, make_user

TODAY = get_settings().today()


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


def offer(client, days, code, **extra):
    data = {"kind": "offer", "day": (TODAY + timedelta(days=days)).isoformat(), "code": code}
    data.update({"start": "18:00", "end": "23:00"}, **extra)
    assert client.post("/plaatsen", data=data).status_code == 200


def shown(client, query=""):
    page = client.get("/aangeboden" + query).text
    with SessionLocal() as s:
        return {lst.note for lst in s.scalars(select(Listing)) if f'id="l{lst.id}"' in page}


def admin_client(name="Ad Min"):
    admin = make_user(name, is_admin=True)
    return admin, login(TestClient(app), admin)


def new_link(a_client, **data):
    page = a_client.post("/beheer/links", data=data).text
    return page.split('id="newlink" value="http://testserver')[1].split('"')[0]
