"""Demo data: made-up colleagues with shifts, so people trying the pilot see a living board.

The demo accounts are remembered in `app_settings` ("demo_user_ids"), so removing them later
deletes exactly those accounts and everything of theirs, never a real colleague. Remove it
from Beheer ("Demo-data verwijderen") or with `python -m app.cli demo-remove`.
"""

import random
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Kind, Listing, Reaction, User, utcnow
from app.services import appdata
from app.services.members import delete_user

KEY = "demo_user_ids"

# Made-up names. Never put real colleagues here: this repository is public.
NAMES = [
    "Sanne de Vries",
    "Daan Bakker",
    "Lotte Visser",
    "Milan Jansen",
    "Fleur Mulder",
    "Thijs de Boer",
    "Noor Smit",
    "Bram Meijer",
    "Eva Hendriks",
    "Sem Dekker",
    "Julia van Dijk",
    "Luuk Bos",
]
TIMES = [
    ("19:10", "22:30"),
    ("18:30", "23:00"),
    ("19:30", "23:15"),
    ("11:30", "15:00"),
    ("13:45", "17:30"),
    ("17:30", "23:45"),
]
OFFER_TYPES = ["H", "HG", "GH", "G", "CGH", "CH", "R", "PH", "PHG"]
NOTES = [
    "",
    "",
    "",
    "Verjaardag van mijn moeder.",
    "Tentamen de dag erna.",
    "Liefst ruilen.",
    "Lange dienst.",
    "Nette kleding.",
    "Kan ook tegen een middagdienst.",
]


def demo_user_ids(db: Session) -> list[int]:
    value = appdata.get_value(db, KEY) or ""
    return [int(x) for x in value.split(",") if x]


def seed(db: Session, today: date, *, rng: random.Random | None = None) -> int:
    """Create the demo colleagues and ~20 shifts over the next two weeks. Returns how many
    accounts were created (0 if demo data already exists)."""
    if demo_user_ids(db):
        return 0
    rng = rng or random.Random(42)
    halls = [h for h in appdata.get_list(db, "halls") if h.lower() != "overig"]
    workplaces = [w for w in appdata.get_list(db, "workplaces") if w.lower() != "overig"]
    now = utcnow()

    taken = {n.lower() for n in db.scalars(select(func.lower(User.name)))}
    users = [User(name=n, created_at=now) for n in NAMES if n.lower() not in taken]
    db.add_all(users)
    db.flush()

    listings = []
    for i in range(16):  # offers
        start, end = rng.choice(TIMES)
        listings.append(
            Listing(
                kind=Kind.OFFER,
                user_id=rng.choice(users).id,
                date=today + timedelta(days=rng.randint(1, 13)),
                start=start,
                end=end,
                shift_type=rng.choice(OFFER_TYPES),
                hall=rng.choice(halls) if halls and rng.random() < 0.8 else None,
                workplace=rng.choice(workplaces) if workplaces and rng.random() < 0.6 else None,
                note=rng.choice(NOTES),
                created_at=now - timedelta(hours=rng.randint(1, 72), minutes=i),
            )
        )
    for i in range(5):  # wanted requests
        listings.append(
            Listing(
                kind=Kind.WANTED,
                user_id=rng.choice(users).id,
                date=today + timedelta(days=rng.randint(1, 13)),
                wanted_types=",".join(rng.sample(OFFER_TYPES, 3)),
                daypart=rng.choice(["avond", "avond", "middag", None]),
                note=rng.choice(NOTES),
                created_at=now - timedelta(hours=rng.randint(1, 48), minutes=i),
            )
        )
    db.add_all(listings)
    db.flush()

    # A few offers already have reactions, so "1 reactie · wacht op …" shows up too.
    for listing in rng.sample([lst for lst in listings if lst.kind == Kind.OFFER], 5):
        others = [u for u in users if u.id != listing.user_id]
        for reactor in rng.sample(others, rng.randint(1, 2)):
            db.add(
                Reaction(
                    listing_id=listing.id,
                    user_id=reactor.id,
                    created_at=listing.created_at + timedelta(minutes=rng.randint(5, 600)),
                )
            )

    appdata.set_value(db, KEY, ",".join(str(u.id) for u in users))  # commits
    return len(users)


def remove(db: Session) -> int:
    """Delete all demo accounts with their shifts and reactions. Real colleagues who reacted
    to a demo shift get the usual "weggehaald" notification. Returns how many were removed."""
    ids = demo_user_ids(db)
    for user in db.scalars(select(User).where(User.id.in_(ids))):
        delete_user(db, user)
    appdata.set_value(db, KEY, None)  # commits
    return len(ids)
