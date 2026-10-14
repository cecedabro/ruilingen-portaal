"""What the boards show: order, posting rank, filters, the day picker, status."""

from datetime import date, timedelta

from sqlalchemy import select

from app.db import SessionLocal
from app.models import (
    Listing,
)
from tests.helpers import (
    TODAY,
    offer,
    shown,
)


def test_board_filters(people):
    _, d = people["daan"]
    _, n = people["noor"]
    offer(d, 2, "HG", start="19:00", end="23:00", hall="Grote Zaal", note="a")
    offer(d, 2, "G", start="09:00", end="12:00", hall="Kleine Zaal", note="b")
    offer(d, 9, "R", start="13:00", end="16:00", note="c")
    _, s_client = people["sanne"]
    assert shown(s_client) == {"a", "b", "c"}
    assert shown(s_client, "?soort=G") == {"a", "b"}  # a letter matches HG too
    assert shown(s_client, "?dagdeel=avond") == {"a"}  # from the start time
    assert shown(s_client, "?dagdeel=ochtend") == {"b"}
    assert shown(s_client, "?zaal=grote zaal") == {"a"}
    # someone reacts to "a": it's no longer "vrij"
    with SessionLocal() as s:
        a_id = s.scalars(select(Listing.id).where(Listing.note == "a")).one()
    n.post(f"/listings/{a_id}/react")
    assert shown(s_client, "?vrij=vrij") == {"b", "c"}
    assert shown(s_client, "?vrij=bezet") == {"a"}
    assert shown(s_client, "?soort=X&dagdeel=nacht") == {"a", "b", "c"}  # junk is ignored


def test_posting_order_is_visible(people):
    _, d = people["daan"]
    _, n = people["noor"]
    offer(d, 9, "H", note="first-posted")
    offer(n, 2, "G", note="second-posted")
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
    offer(d, 5, "H", note="later")
    offer(d, 2, "H", start="19:00", end="23:00", note="avond")
    offer(d, 2, "H", start="10:00", end="14:00", note="ochtend")
    _, s_client = people["sanne"]
    page = s_client.get("/aangeboden").text
    assert page.index("ochtend</dd>") < page.index("avond</dd>") < page.index("later</dd>")


def test_pending_status_is_visible_to_others(people):
    _, d = people["daan"]
    _, n = people["noor"]
    _, s_client = people["sanne"]
    offer(d, 3, "H")
    with SessionLocal() as s:
        lid = s.scalars(select(Listing.id)).one()
    assert "Overnemen" in s_client.get("/aangeboden").text
    n.post(f"/listings/{lid}/react")
    page = s_client.get("/aangeboden").text
    assert "1 reactie · wacht op Daan" in page and "Reageer als 2e" in page
    assert "je bent de eerste" in n.get("/aangeboden").text
    s_client.post(f"/listings/{lid}/react")
    assert "je bent 2e" in s_client.get("/aangeboden").text


def test_roster_horizon_follows_tuesday_release():
    from app.services.board import roster_horizon

    monday, tuesday, sunday = date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 18)
    assert roster_horizon(monday, 1) == sunday  # next week's rooster isn't out yet
    assert roster_horizon(tuesday, 1) == sunday + timedelta(days=7)  # it is now
    assert roster_horizon(sunday, 1) == sunday + timedelta(days=7)


def test_day_choices_are_whole_weeks_from_this_monday():
    from app.services.board import day_choices

    tuesday = date(2026, 10, 13)
    weeks = day_choices(tuesday, [], set(), 1)
    assert len(weeks) == 2 and all(len(w) == 7 for w in weeks)
    assert weeks[0][0].day == date(2026, 10, 12) and not weeks[0][0].selectable  # monday, past
    assert weeks[0][1].selectable and weeks[-1][-1].day == date(2026, 10, 25)


def test_filter_on_specific_days(people):
    _, d = people["daan"]
    offer(d, 1, "H", note="one")
    offer(d, 2, "H", note="two")
    offer(d, 3, "H", note="three")
    _, s_client = people["sanne"]
    d1, d3 = (TODAY + timedelta(days=1)).isoformat(), (TODAY + timedelta(days=3)).isoformat()
    assert shown(s_client, f"?dag={d1}&dag={d3}") == {"one", "three"}
    page = s_client.get("/aangeboden").text
    assert f'value="{d1}"' in page  # offered in the picker
    assert shown(s_client, "?dag=not-a-date") == {"one", "two", "three"}


def test_posting_time_not_shown_on_board(people):
    _, d = people["daan"]
    offer(d, 2, "H")
    _, s_client = people["sanne"]
    assert "vandaag " not in s_client.get("/aangeboden").text
