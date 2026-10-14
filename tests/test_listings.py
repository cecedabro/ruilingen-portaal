"""Posting, reacting, confirming: the swap rules, including the race on confirming."""

import threading
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import mail
from app.db import SessionLocal
from app.main import app
from app.models import (
    Kind,
    Listing,
    ListingStatus,
    ReactionStatus,
    User,
)
from app.services import listings, transaction
from app.services.errors import UserError
from tests.conftest import join
from tests.helpers import (
    TODAY,
    notifications_for,
    offer,
    post_offer,
    reactions,
    shown,
)


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
    assert "begin- en eindtijd" in r.text
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
                transaction.run_write(s, listings.accept, user, rid, today=TODAY)
                results.append("ok")
            except UserError as e:
                results.append(str(e))

    threads = [threading.Thread(target=go, args=(rid,)) for rid in ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count("ok") == 1, results
    statuses = sorted(r.status for r in reactions(listing.id))
    assert statuses == [ReactionStatus.ACCEPTED, ReactionStatus.EXPIRED]


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


def test_offer_needs_type_date_and_time(people):
    _, client = people["daan"]
    day = (TODAY + timedelta(days=3)).isoformat()
    r = client.post("/plaatsen", data={"kind": "offer", "day": day, "code": "HG"})
    assert r.status_code == 422 and "begin- en eindtijd" in r.text
    r = client.post(
        "/plaatsen", data={"kind": "offer", "day": day, "start": "18:00", "end": "23:00"}
    )
    assert r.status_code == 422 and "soort dienst" in r.text
    r = client.post(
        "/plaatsen",
        data={"kind": "offer", "day": day, "code": "HG", "start": "18:00", "end": "23:00"},
    )
    assert r.status_code == 200
    with SessionLocal() as s:
        listing = s.scalars(select(Listing)).one()
        assert (listing.hall, listing.workplace) == (None, None)  # still optional


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
    # zaal and werkplek are choices from the admin lists, not free text
    r = client.post(
        "/plaatsen",
        data={
            "kind": "offer",
            "day": day,
            "code": "H",
            "start": "19:10",
            "end": "22:30",
            "hall": "Zolder",
        },
    )
    assert r.status_code == 422 and "zaal uit de lijst" in r.text


def test_half_a_time_is_rejected(people):
    _, client = people["daan"]
    day = (TODAY + timedelta(days=3)).isoformat()
    r = client.post("/plaatsen", data={"kind": "offer", "day": day, "code": "H", "start": "19:00"})
    assert r.status_code == 422 and "begin- en eindtijd" in r.text


def test_wanted_reply_needs_type_and_time(people):
    noor, n_client = people["noor"]
    _, s_client = people["sanne"]
    day = (TODAY + timedelta(days=4)).isoformat()
    n_client.post(
        "/plaatsen", data={"kind": "wanted", "day": day, "codes": ["H"], "daypart": "avond"}
    )
    with SessionLocal() as s:
        listing = s.scalars(select(Listing)).one()
        assert listing.daypart == "avond"  # a wanted request keeps an optional dagdeel
    r = s_client.post(
        f"/listings/{listing.id}/react", data={"offer_type": "HG"}, follow_redirects=True
    )
    assert "begin- en eindtijd" in r.text and reactions(listing.id) == []
    s_client.post(
        f"/listings/{listing.id}/react",
        data={
            "offer_type": "HG",
            "offer_start": "19:00",
            "offer_end": "23:00",
            "offer_hall": "Grote Zaal",
        },
    )
    r = reactions(listing.id)[0]
    assert (r.offer_type, r.offer_start, r.offer_hall) == ("HG", "19:00", "Grote Zaal")


def test_inwerk_is_a_shift_type(people):
    _, d = people["daan"]
    offer(d, 2, "Inwerk", note="inwerk")
    _, s_client = people["sanne"]
    assert shown(s_client, "?soort=I") == {"inwerk"}
    assert ">Inwerk<" in s_client.get("/aangeboden").text
