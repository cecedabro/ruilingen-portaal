"""What the boards and the tab bar show: open listings, filters, the day picker, counts."""

import contextlib
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Kind, Listing, ListingStatus, Notification, Reaction, ReactionStatus, User
from app.services.listings import Deal
from app.shifts import DAYPARTS

FILTER_LETTERS = ("H", "G", "C", "P", "R", "I")  # "H" matches H, HG, PGH, ...; "I" = Inwerk
MAX_PICKER_WEEKS = 8


def _with_people(stmt):
    """Load the poster and reactions (with their users) in two extra queries, not N."""
    return stmt.options(
        selectinload(Listing.user),
        selectinload(Listing.reactions).selectinload(Reaction.user),
    )


# ---------------------------------------------------------------- listings


def open_listings(db: Session, kind: Kind, today: date) -> list[Listing]:
    """Open listings from today on, in shift order: date, then time, then who posted first."""
    stmt = select(Listing).where(
        Listing.kind == kind, Listing.status == ListingStatus.OPEN, Listing.date >= today
    )
    items = list(db.scalars(_with_people(stmt)))
    items.sort(key=lambda lst: (lst.date, lst.info.sort_key, lst.created_at))
    return items


def posting_ranks(listings: list[Listing]) -> dict[int, int]:
    """#1, #2, ...: order of posting over the whole board (colleagues care who was first).
    Computed before filtering, so a filter never changes someone's number."""
    by_posting = sorted(listings, key=lambda lst: (lst.created_at, lst.id))
    return {lst.id: rank for rank, lst in enumerate(by_posting, start=1)}


def my_listings(db: Session, user: User, today: date) -> list[Listing]:
    """For "Mijn": what the user posted or reacted to that's still relevant. Open ones first,
    then completed swaps the user is part of (until housekeeping removes them)."""
    reacted = select(Reaction.listing_id).where(Reaction.user_id == user.id)
    stmt = select(Listing).where(
        or_(Listing.user_id == user.id, Listing.id.in_(reacted)),
        Listing.status != ListingStatus.REMOVED,
        or_(Listing.date >= today, Listing.status == ListingStatus.TAKEN),
    )
    items = [
        lst
        for lst in db.scalars(_with_people(stmt))
        if lst.status == ListingStatus.OPEN or ((deal := Deal.of(lst)) and deal.involves(user))
    ]
    items.sort(key=lambda lst: (lst.status == ListingStatus.TAKEN, lst.date, lst.info.sort_key))
    return items


# ---------------------------------------------------------------- filters


@dataclass(frozen=True)
class BoardFilter:
    """Board filters as they come from the query string; empty means "no filter". Unknown
    values are dropped, so a hand-edited URL can't break the page."""

    soort: str = ""
    dagdeel: str = ""
    zaal: str = ""
    vrij: str = ""  # "vrij" = nobody reacted yet, "bezet" = someone did
    dagen: frozenset[date] = frozenset()

    @classmethod
    def parse(cls, soort="", dagdeel="", zaal="", vrij="", dagen=()) -> "BoardFilter":
        days = set()
        for value in list(dagen)[: 7 * MAX_PICKER_WEEKS]:
            with contextlib.suppress(ValueError):
                days.add(date.fromisoformat(value))
        return cls(
            soort=soort if soort in FILTER_LETTERS else "",
            dagdeel=dagdeel if dagdeel in DAYPARTS else "",
            zaal=" ".join(zaal.split())[:60],
            vrij=vrij if vrij in ("vrij", "bezet") else "",
            dagen=frozenset(days),
        )

    @property
    def active(self) -> bool:
        return any((self.soort, self.dagdeel, self.zaal, self.vrij, self.dagen))

    def matches(self, listing: Listing) -> bool:
        types = (listing.shift_type or "") + "".join(listing.wanted_type_list)
        taken = bool(listing.pending_reactions)
        return not (
            (self.soort and self.soort not in types)
            or (self.dagdeel and listing.info.part_of_day != self.dagdeel)
            or (self.zaal and (listing.hall or "").lower() != self.zaal.lower())
            or (self.vrij == "vrij" and taken)
            or (self.vrij == "bezet" and not taken)
            or (self.dagen and listing.date not in self.dagen)
        )

    def apply(self, listings: list[Listing]) -> list[Listing]:
        return [lst for lst in listings if self.matches(lst)]


# ---------------------------------------------------------------- day picker


def roster_horizon(today: date, release_weekday: int) -> date:
    """Last day of the latest published rooster. Roosters come out on `release_weekday`
    for the week after, so from that day on it's next week's sunday, before it this sunday."""
    sunday = today + timedelta(days=6 - today.weekday())
    return sunday + timedelta(days=7) if today.weekday() >= release_weekday else sunday


@dataclass
class DayChoice:
    day: date
    selectable: bool  # false before today (shown greyed out, to keep weeks aligned)
    count: int  # listings on the board that day
    selected: bool


def day_choices(
    today: date, listings: list[Listing], selected: frozenset[date], release_weekday: int
) -> list[list[DayChoice]]:
    """Whole weeks (monday–sunday) from this week to the end of the latest rooster, or to the
    furthest posted shift if that's later (capped at MAX_PICKER_WEEKS)."""
    last = roster_horizon(today, release_weekday)
    if listings:
        last = max(last, max(lst.date for lst in listings))
    last = min(last, today + timedelta(weeks=MAX_PICKER_WEEKS))
    counts: dict[date, int] = {}
    for lst in listings:
        counts[lst.date] = counts.get(lst.date, 0) + 1

    weeks, monday = [], today - timedelta(days=today.weekday())
    while monday <= last:
        days = (monday + timedelta(days=i) for i in range(7))
        weeks.append([DayChoice(d, d >= today, counts.get(d, 0), d in selected) for d in days])
        monday += timedelta(days=7)
    return weeks


# ---------------------------------------------------------------- tab bar and bell


@dataclass
class NavCounts:
    offers: int  # open "Aangeboden"
    wanted: int  # open "Gezocht"
    todo: int  # reactions waiting for this user's decision ("Mijn" badge)
    unread: int  # unread notifications (bell)


def nav_counts(db: Session, user: User, today: date) -> NavCounts:
    open_now = (Listing.status == ListingStatus.OPEN, Listing.date >= today)
    per_kind = dict(
        db.execute(
            select(Listing.kind, func.count(Listing.id)).where(*open_now).group_by(Listing.kind)
        ).all()
    )
    todo = db.scalar(
        select(func.count(Reaction.id))
        .join(Listing)
        .where(Listing.user_id == user.id, Reaction.status == ReactionStatus.PENDING, *open_now)
    )
    unread = db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id, Notification.read_at.is_(None)
        )
    )
    return NavCounts(per_kind.get(Kind.OFFER, 0), per_kind.get(Kind.WANTED, 0), todo, unread)
