"""Swaps (ruilen): offers that want a shift back, proposals, and the completed swap."""

from datetime import timedelta

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Listing, ListingStatus, Mode, Reaction
from tests.helpers import TODAY, notifications_for, post_offer, reactions

DAY = TODAY + timedelta(days=5)


def _proposal(day=DAY, **extra):
    data = {
        "offer_type": "H",
        "offer_date": day.isoformat(),
        "offer_start": "19:00",
        "offer_end": "23:00",
    }
    data.update(extra)
    return data


def test_trade_offer_shows_label_and_wish(people):
    _, d = people["daan"]
    _, s = people["sanne"]
    post_offer(
        d,
        mode="trade",
        want_from=DAY.isoformat(),
        want_to=(DAY + timedelta(2)).isoformat(),
        want_types=["H", "HG"],
        note="Liefst een avond.",
    )
    page = s.get("/aangeboden").text
    assert ">ruil<" in page and "Ruil voorstellen" in page
    assert "Daan zoekt terug:" in page and "H, HG" in page
    assert "Overnemen" not in page  # a swap-only offer can't just be taken
    with SessionLocal() as db:
        assert db.scalars(select(Listing)).one().mode == Mode.TRADE


def test_give_ignores_wish_fields_and_both_allows_either(people):
    _, d = people["daan"]
    _, s = people["sanne"]
    give = post_offer(d, want_types=["H"], mode="give")
    both = post_offer(d, mode="both", day=DAY)
    with SessionLocal() as db:
        assert db.get(Listing, give.id).want_types is None
        assert db.get(Listing, both.id).mode == Mode.BOTH
    page = s.get("/aangeboden").text
    assert ">ruil of weg<" in page and "Overnemen" in page and "Ruil voorstellen" in page
    # both: a plain reaction (no shift back) works
    s.post(f"/listings/{both.id}/react")
    assert reactions(both.id)[0].offer_type is None


def test_trade_needs_a_shift_back(people):
    _, d = people["daan"]
    _, s = people["sanne"]
    listing = post_offer(d, mode="trade")
    r = s.post(f"/listings/{listing.id}/react", follow_redirects=True)
    assert "soort dienst die je teruggeeft" in r.text and reactions(listing.id) == []
    r = s.post(
        f"/listings/{listing.id}/react", data=_proposal(offer_date=""), follow_redirects=True
    )
    assert "datum van de dienst die je teruggeeft" in r.text
    r = s.post(
        f"/listings/{listing.id}/react", data=_proposal(offer_start=""), follow_redirects=True
    )
    assert "begin- en eindtijd" in r.text


def test_proposal_confirmed_makes_a_two_shift_swap(people):
    daan, d = people["daan"]
    sanne, s = people["sanne"]
    listing = post_offer(d, mode="trade", code="CGH", start="17:30", end="23:45")
    s.post(f"/listings/{listing.id}/react", data=_proposal(offer_hall="Grote Zaal"))
    reaction = reactions(listing.id)[0]
    assert (reaction.offer_type, reaction.offer_date) == ("H", DAY)
    assert any("stelt een ruil voor" in t for t in notifications_for(daan))

    owner_page = d.get("/mijn").text
    assert "biedt in ruil" in owner_page and "19:00 – 23:00" in owner_page
    d.post(f"/reactions/{reaction.id}/accept")

    page = s.get("/mijn").text
    assert "Jij ruilt met Daan Bakker" in page
    assert "Daan Bakker geeft" in page and "Jij geeft" in page
    # the email to planning lists both shifts
    assert "Daan Bakker en Sanne de Vries ruilen de volgende diensten" in page
    assert "Sanne de Vries neemt over van Daan Bakker" in page
    assert "Daan Bakker neemt over van Sanne de Vries" in page
    assert "Soort:    CGH" in page and "Soort:    H" in page and "Zaal:     Grote Zaal" in page
    assert "↔" in page  # the swap subject


def test_proposal_outside_the_wish_is_allowed_with_a_hint(people):
    _, d = people["daan"]
    _, s = people["sanne"]
    listing = post_offer(
        d, mode="trade", want_types=["HG"], want_to=(DAY - timedelta(1)).isoformat()
    )
    s.post(f"/listings/{listing.id}/react", data=_proposal())  # wrong type and too late
    assert len(reactions(listing.id)) == 1
    assert "buiten je wens" in d.get("/mijn").text
    # inside the wish: no hint
    other = post_offer(d, mode="trade", want_types=["H"], day=DAY + timedelta(1))
    s.post(f"/listings/{other.id}/react", data=_proposal())
    assert d.get("/mijn").text.count("buiten je wens") == 1


def test_picking_your_own_offer_closes_it_after_the_swap(people):
    daan, d = people["daan"]
    sanne, s = people["sanne"]
    noor, n = people["noor"]
    target = post_offer(d, mode="trade", code="CGH")
    mine = post_offer(s, day=DAY, code="H", start="19:00", end="23:00")  # Sanne's own offer
    n.post(f"/listings/{mine.id}/react")  # someone else wants Sanne's shift
    assert f'value="{mine.id}"' in s.get("/aangeboden").text  # offered in the dropdown

    s.post(f"/listings/{target.id}/react", data={"offer_listing_id": str(mine.id)})
    reaction = [r for r in reactions(target.id)][0]
    assert (reaction.offer_listing_id, reaction.offer_type, reaction.offer_date) == (
        mine.id,
        "H",
        DAY,
    )
    d.post(f"/reactions/{reaction.id}/accept")

    with SessionLocal() as db:
        assert db.get(Listing, mine.id).status == ListingStatus.REMOVED
        assert (
            db.scalars(select(Reaction).where(Reaction.listing_id == mine.id)).one().status
            == "expired"
        )
    assert any("is geruild" in t for t in notifications_for(noor))


def test_cannot_pick_someone_elses_or_the_same_offer(people):
    _, d = people["daan"]
    _, s = people["sanne"]
    _, n = people["noor"]
    target = post_offer(d, mode="trade")
    theirs = post_offer(n, day=DAY)
    r = s.post(
        f"/listings/{target.id}/react",
        data={"offer_listing_id": str(theirs.id)},
        follow_redirects=True,
    )
    assert "eigen aangeboden diensten" in r.text
    own_trade = post_offer(s, mode="trade", day=DAY)
    r = s.post(
        f"/listings/{own_trade.id}/react",
        data={"offer_listing_id": str(own_trade.id)},
        follow_redirects=True,
    )
    assert "eigen dienst" in r.text  # you can't react to yourself


def test_wanted_reply_can_use_an_own_offer(people):
    _, n = people["noor"]
    _, s = people["sanne"]
    n.post("/plaatsen", data={"kind": "wanted", "day": DAY.isoformat(), "codes": ["H"]})
    with SessionLocal() as db:
        wanted = db.scalars(select(Listing).where(Listing.kind == "wanted")).one()
    mine = post_offer(s, day=DAY, code="H")
    s.post(f"/listings/{wanted.id}/react", data={"offer_listing_id": str(mine.id)})
    reaction = reactions(wanted.id)[0]
    assert (reaction.offer_listing_id, reaction.offer_date) == (mine.id, DAY)
    n.post(f"/reactions/{reaction.id}/accept")
    with SessionLocal() as db:
        assert db.get(Listing, mine.id).status == ListingStatus.REMOVED


def test_wish_validation(people):
    _, d = people["daan"]
    r = d.post(
        "/plaatsen",
        data={
            "kind": "offer",
            "day": DAY.isoformat(),
            "code": "H",
            "start": "18:00",
            "end": "22:00",
            "mode": "trade",
            "want_from": DAY.isoformat(),
            "want_to": (DAY - timedelta(1)).isoformat(),
        },
    )
    assert r.status_code == 422 and "einddatum van je wens" in r.text


def test_wanted_reply_only_offers_shifts_of_the_same_day(people):
    _, n = people["noor"]
    _, s = people["sanne"]
    n.post("/plaatsen", data={"kind": "wanted", "day": DAY.isoformat(), "codes": ["H"]})
    with SessionLocal() as db:
        wanted = db.scalars(select(Listing).where(Listing.kind == "wanted")).one()
    same_day = post_offer(s, day=DAY, code="H")
    other_day = post_offer(s, day=DAY + timedelta(days=1), code="G")

    page = s.get("/gezocht").text  # the dropdown on a wanted request: same day only
    assert f'value="{same_day.id}"' in page and f'value="{other_day.id}"' not in page

    r = s.post(
        f"/listings/{wanted.id}/react",
        data={"offer_listing_id": str(other_day.id)},
        follow_redirects=True,
    )
    assert "voor één dag" in r.text and reactions(wanted.id) == []

    # a swap offer, on the other hand, can be answered with a shift of any day
    target = post_offer(people["daan"][1], mode="trade", day=DAY + timedelta(days=2))
    assert f'value="{other_day.id}"' in s.get("/aangeboden").text
    s.post(f"/listings/{target.id}/react", data={"offer_listing_id": str(other_day.id)})
    assert reactions(target.id)[0].offer_listing_id == other_day.id
