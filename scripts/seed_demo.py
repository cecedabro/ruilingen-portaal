"""Fill a local database with the made-up colleagues and shifts from the prototype.

    .venv/bin/python -m scripts.seed_demo

Refuses to run against a database that already has users. Never use real names here.
"""

from datetime import timedelta

from sqlalchemy import func, select

from app.config import get_settings
from app.db import SessionLocal
from app.models import Kind, Listing, Reaction, User, utcnow
from app.services import local_today

PEOPLE = [
    "Sanne de Vries",
    "Daan Bakker",
    "Lotte Visser",
    "Milan Jansen",
    "Fleur Mulder",
    "Thijs de Boer",
    "Noor Smit",
    "Bram Meijer",
]


def email_for(name: str) -> str:
    return name.lower().replace(" de ", ".de.").replace(" ", ".") + "@voorbeeld.nl"


def main() -> None:
    settings = get_settings()
    today = local_today(settings)
    now = utcnow()
    with SessionLocal() as db:
        if db.scalar(select(func.count(User.id))):
            raise SystemExit("Database already has users; not seeding.")
        users = [User(name=n, email=email_for(n), is_admin=(i == 1)) for i, n in enumerate(PEOPLE)]
        db.add_all(users)
        db.flush()
        u = {p.split()[0]: users[i] for i, p in enumerate(PEOPLE)}

        def ago(minutes: int):
            return now - timedelta(minutes=minutes)

        def day(n: int):
            return today + timedelta(days=n)

        offers = [
            Listing(
                kind=Kind.OFFER,
                user_id=u["Daan"].id,
                date=day(3),
                start="18:00",
                end="23:30",
                shift_type="HG",
                note="Verjaardag van mijn moeder.",
                created_at=ago(60 * 26),
            ),
            Listing(
                kind=Kind.OFFER,
                user_id=u["Fleur"].id,
                date=day(5),
                start="19:00",
                end="23:00",
                shift_type="G",
                created_at=ago(60 * 20),
            ),
            Listing(
                kind=Kind.OFFER,
                user_id=u["Lotte"].id,
                date=day(5),
                start="17:30",
                end="23:45",
                shift_type="CGH",
                note="Lange dienst, zaterdagconcert.",
                created_at=ago(60 * 8),
            ),
            Listing(
                kind=Kind.OFFER,
                user_id=u["Thijs"].id,
                date=day(9),
                start="11:30",
                end="15:00",
                shift_type="R",
                note="Receptie bij een matinee. Nette kleding.",
                created_at=ago(95),
            ),
            Listing(
                kind=Kind.OFFER,
                user_id=u["Bram"].id,
                date=day(12),
                start="19:15",
                end="22:45",
                shift_type="PH",
                created_at=ago(40),
            ),
        ]
        wanted = [
            Listing(
                kind=Kind.WANTED,
                user_id=u["Noor"].id,
                date=day(4),
                wanted_types="H,G,HG,GH",
                note="Zoek een avonddienst, maakt niet uit welke.",
                created_at=ago(60 * 30),
            ),
            Listing(
                kind=Kind.WANTED,
                user_id=u["Milan"].id,
                date=day(6),
                wanted_types="CH,CGH,CHG",
                note="Graag champagne erbij.",
                created_at=ago(60 * 5),
            ),
            Listing(
                kind=Kind.WANTED,
                user_id=u["Sanne"].id,
                date=day(10),
                wanted_types="R,PH,PHG,PGH",
                created_at=ago(30),
            ),
        ]
        db.add_all(offers + wanted)
        db.flush()
        db.add_all(
            [
                Reaction(listing_id=offers[0].id, user_id=u["Noor"].id, created_at=ago(60 * 25)),
                Reaction(listing_id=offers[0].id, user_id=u["Sanne"].id, created_at=ago(60 * 3)),
                Reaction(listing_id=offers[2].id, user_id=u["Milan"].id, created_at=ago(60 * 7)),
                Reaction(
                    listing_id=wanted[0].id,
                    user_id=u["Fleur"].id,
                    created_at=ago(60 * 19),
                    offer_start="19:00",
                    offer_end="23:00",
                    offer_type="G",
                ),
            ]
        )
        db.commit()
    print("Seeded. Log in as e.g.", email_for("Daan Bakker"), "(admin)")


if __name__ == "__main__":
    main()
