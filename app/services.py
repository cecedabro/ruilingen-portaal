"""Everything that changes swap state lives here, so the rules are in one place.

Concurrency: SQLite runs one writer at a time, and in WAL mode a transaction that read old data
and then tries to write fails instead of overwriting someone else's change. `run_write` starts
every change on a fresh transaction and retries on such a conflict, and `accept` additionally
flips the listing with a conditional UPDATE, so a listing can never be given away twice.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TypeVar

from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, selectinload

from app.config import Settings, get_settings
from app.models import (
    Kind,
    Listing,
    ListingStatus,
    LoginToken,
    Notification,
    Reaction,
    ReactionStatus,
    User,
    utcnow,
)
from app.shifts import DAYPARTS, ShiftInfo, fmt_date, is_shift_type, is_time

MAX_OPEN_LISTINGS = 30
MAX_NOTE = 200

T = TypeVar("T")


class SwapError(Exception):
    """A rule was broken; the message is shown to the user as is (Dutch)."""


@dataclass
class QueuedMail:
    to: str
    subject: str
    body: str


def run_write(db: Session, fn: Callable[..., T], *args, **kwargs) -> T:
    for attempt in range(4):
        db.rollback()  # end any read transaction so we start from the latest data
        db.info["mails"] = []
        try:
            result = fn(db, *args, **kwargs)
            db.commit()
            return result
        except OperationalError as e:
            db.rollback()
            if "locked" not in str(e) or attempt == 3:
                raise
            time.sleep(0.05 * (attempt + 1))
        except Exception:
            db.rollback()
            raise
    raise AssertionError("unreachable")


def queued_mails(db: Session) -> list[QueuedMail]:
    return db.info.pop("mails", [])


def notify(db: Session, user: User, text: str, link: str = "/mijn") -> None:
    db.add(Notification(user_id=user.id, text=text, link=link))
    settings = get_settings()
    if user.email and user.email_notifications and user.is_active and settings.mail_enabled:
        base = settings.base_url
        body = (
            f"Hoi {user.first_name},\n\n{text}\n\nBekijk het op {base}{link}\n\n"
            f"Geen mails meer van ons? Zet ze uit op {base}/account"
        )
        db.info.setdefault("mails", []).append(QueuedMail(user.email, text, body))


# ---------------------------------------------------------------- creating listings


def _check_date(day: date, today: date) -> None:
    if day < today:
        raise SwapError("Die datum is al voorbij.")
    if day > today + timedelta(days=366):
        raise SwapError("Zo ver vooruit kan niet.")


def _check_note(note: str) -> str:
    note = (note or "").strip()
    if len(note) > MAX_NOTE:
        raise SwapError(f"De toelichting mag maximaal {MAX_NOTE} tekens zijn.")
    return note


def _check_capacity(db: Session, user: User, today: date) -> None:
    n = db.scalar(
        select(Listing.id)
        .where(Listing.user_id == user.id, Listing.status == ListingStatus.OPEN)
        .where(Listing.date >= today)
        .offset(MAX_OPEN_LISTINGS - 1)
        .limit(1)
    )
    if n is not None:
        raise SwapError(f"Je hebt al {MAX_OPEN_LISTINGS} open diensten staan.")


def shift_details(
    *,
    start: str | None = None,
    end: str | None = None,
    daypart: str | None = None,
    hall: str | None = None,
    workplace: str | None = None,
) -> dict:
    """The optional when/where of a shift. Either a time (both ends), or a part of the day, or
    nothing at all; zaal and werkplek are free text."""
    start, end = (start or "").strip(), (end or "").strip()
    if start or end:
        if not (is_time(start) and is_time(end)):
            raise SwapError("Vul zowel een begin- als eindtijd in, of laat ze allebei leeg.")
        if start == end:
            raise SwapError("Begin- en eindtijd zijn gelijk.")
        daypart = None  # the time says it all
    else:
        start = end = None
        daypart = daypart if daypart in DAYPARTS else None

    def short(value: str | None, label: str) -> str | None:
        value = " ".join((value or "").split())
        if len(value) > 60:
            raise SwapError(f"{label} mag maximaal 60 tekens zijn.")
        return value or None

    return {
        "start": start,
        "end": end,
        "daypart": daypart,
        "hall": short(hall, "Zaal"),
        "workplace": short(workplace, "Werkplek"),
    }


def create_offer(
    db: Session, user: User, *, day: date, code: str, note: str, today: date, **details
) -> Listing:
    _check_date(day, today)
    if not is_shift_type(code):
        raise SwapError("Kies een soort dienst.")
    fields = shift_details(**details)
    _check_capacity(db, user, today)
    listing = Listing(
        kind=Kind.OFFER,
        user_id=user.id,
        date=day,
        shift_type=code,
        note=_check_note(note),
        **fields,
    )
    db.add(listing)
    db.flush()
    return listing


def create_wanted(
    db: Session,
    user: User,
    *,
    day: date,
    codes: list[str],
    note: str,
    today: date,
    daypart: str | None = None,
) -> Listing:
    _check_date(day, today)
    codes = [c for c in dict.fromkeys(codes) if is_shift_type(c)]
    if not codes:
        raise SwapError("Kies minstens één soort dienst.")
    _check_capacity(db, user, today)
    listing = Listing(
        kind=Kind.WANTED,
        user_id=user.id,
        date=day,
        wanted_types=",".join(codes),
        daypart=daypart if daypart in DAYPARTS else None,
        note=_check_note(note),
    )
    db.add(listing)
    db.flush()
    return listing


# ---------------------------------------------------------------- reacting


def _open_listing(db: Session, listing_id: int, today: date) -> Listing:
    listing = db.get(Listing, listing_id)
    if listing is None or listing.status == ListingStatus.REMOVED:
        raise SwapError("Deze dienst bestaat niet meer.")
    if listing.status == ListingStatus.TAKEN:
        raise SwapError("Deze dienst is net vergeven.")
    if listing.date < today:
        raise SwapError("Deze dienst is al voorbij.")
    return listing


def react(
    db: Session,
    user: User,
    listing_id: int,
    *,
    today: date,
    offer_type: str | None = None,
    offer_start: str | None = None,
    offer_end: str | None = None,
    offer_daypart: str | None = None,
    offer_hall: str | None = None,
    offer_workplace: str | None = None,
) -> Reaction:
    listing = _open_listing(db, listing_id, today)
    if listing.user_id == user.id:
        raise SwapError("Je kunt niet op je eigen dienst reageren.")
    reaction = Reaction(listing_id=listing.id, user_id=user.id)
    if listing.kind == Kind.WANTED:
        if not (offer_type and is_shift_type(offer_type)):
            raise SwapError("Kies de soort dienst die je aanbiedt.")
        fields = shift_details(
            start=offer_start,
            end=offer_end,
            daypart=offer_daypart,
            hall=offer_hall,
            workplace=offer_workplace,
        )
        reaction.offer_type = offer_type
        for key, value in fields.items():
            setattr(reaction, f"offer_{key}", value)
    db.add(reaction)
    try:
        db.flush()
    except IntegrityError:
        raise SwapError("Je hebt hier al op gereageerd.") from None

    owner = listing.user
    when = fmt_date(listing.date)
    if listing.kind == Kind.OFFER:
        notify(db, owner, f"{user.name} wil je {listing.shift_type}-dienst van {when} overnemen.")
    else:
        notify(db, owner, f"{user.name} biedt je een {offer_type}-dienst aan op {when}.")
    return reaction


def _own_pending_reaction(db: Session, user: User, reaction_id: int) -> Reaction:
    reaction = db.get(Reaction, reaction_id)
    if reaction is None or reaction.user_id != user.id:
        raise SwapError("Reactie niet gevonden.")
    if reaction.status != ReactionStatus.PENDING:
        raise SwapError("Deze reactie loopt niet meer.")
    return reaction


def withdraw(db: Session, user: User, reaction_id: int) -> None:
    reaction = _own_pending_reaction(db, user, reaction_id)
    reaction.status = ReactionStatus.WITHDRAWN
    reaction.decided_at = utcnow()


def _pending_on_my_listing(db: Session, user: User, reaction_id: int) -> Reaction:
    reaction = db.get(Reaction, reaction_id)
    if reaction is None or reaction.listing.user_id != user.id:
        raise SwapError("Reactie niet gevonden.")
    if reaction.status != ReactionStatus.PENDING:
        raise SwapError("Deze reactie is ingetrokken of al afgehandeld.")
    return reaction


def decline(db: Session, user: User, reaction_id: int) -> None:
    reaction = _pending_on_my_listing(db, user, reaction_id)
    reaction.status = ReactionStatus.DECLINED
    reaction.decided_at = utcnow()
    notify(
        db,
        reaction.user,
        f"{user.name} heeft je reactie op {fmt_date(reaction.listing.date)} afgewezen.",
    )


def accept(db: Session, user: User, reaction_id: int, *, today: date) -> Listing:
    reaction = _pending_on_my_listing(db, user, reaction_id)
    listing = _open_listing(db, reaction.listing_id, today)
    now = utcnow()

    # The conditional UPDATEs are the real guard: only one transaction can move the listing
    # from open to taken, and only a still-pending reaction can be accepted.
    flipped = db.execute(
        update(Listing)
        .where(Listing.id == listing.id, Listing.status == ListingStatus.OPEN)
        .values(status=ListingStatus.TAKEN, closed_at=now)
    ).rowcount
    if flipped != 1:
        raise SwapError("Deze dienst is net vergeven.")
    chosen = db.execute(
        update(Reaction)
        .where(Reaction.id == reaction.id, Reaction.status == ReactionStatus.PENDING)
        .values(status=ReactionStatus.ACCEPTED, decided_at=now)
    ).rowcount
    if chosen != 1:
        raise SwapError("Deze reactie is net ingetrokken.")
    db.expire_all()  # the UPDATEs bypassed the ORM; reload what we read next

    when = fmt_date(listing.date)
    for other in listing.pending_reactions:
        other.status = ReactionStatus.EXPIRED
        other.decided_at = now
        notify(db, other.user, f"De dienst van {when} is aan iemand anders gegeven.", "/mijn")
    notify(
        db,
        reaction.user,
        f"{user.name} heeft bevestigd: de ruil van {when} is rond. "
        "Stuur de mail naar planning vanuit Mijn ruilen.",
    )
    return listing


def remove_listing(db: Session, user: User, listing_id: int) -> None:
    listing = db.get(Listing, listing_id)
    if listing is None or listing.user_id != user.id:
        raise SwapError("Dienst niet gevonden.")
    if listing.status != ListingStatus.OPEN:
        raise SwapError("Deze dienst is al afgesloten.")
    now = utcnow()
    listing.status = ListingStatus.REMOVED
    listing.closed_at = now
    for other in listing.pending_reactions:
        other.status = ReactionStatus.EXPIRED
        other.decided_at = now
        notify(
            db, other.user, f"{user.name} heeft de dienst van {fmt_date(listing.date)} weggehaald."
        )


def mark_mail_sent(db: Session, user: User, listing_id: int) -> None:
    listing = db.get(Listing, listing_id)
    deal = listing and listing.status == ListingStatus.TAKEN and Deal.of(listing)
    if not deal or user.id not in (deal.giver.id, deal.taker.id):
        raise SwapError("Ruil niet gevonden.")
    if listing.mail_sent_at is None:
        listing.mail_sent_at = utcnow()
        listing.mail_sent_by_id = user.id
        other = deal.taker if user.id == deal.giver.id else deal.giver
        notify(
            db,
            other,
            f"{user.name} heeft de ruil van {fmt_date(listing.date)} naar planning gemaild.",
        )


# ---------------------------------------------------------------- reading


@dataclass
class Deal:
    """A completed swap, seen as giver → taker regardless of who posted what."""

    listing: Listing
    reaction: Reaction
    giver: User
    taker: User
    shift: ShiftInfo

    @classmethod
    def of(cls, listing: Listing) -> "Deal | None":
        r = listing.accepted_reaction
        if r is None:
            return None
        if listing.kind == Kind.OFFER:
            return cls(listing, r, listing.user, r.user, listing.info)
        return cls(listing, r, r.user, listing.user, r.offer_info)


def _with_reactions(stmt):
    return stmt.options(
        selectinload(Listing.user),
        selectinload(Listing.reactions).selectinload(Reaction.user),
    )


def open_listings(db: Session, kind: Kind, today: date) -> list[Listing]:
    stmt = (
        select(Listing)
        .where(Listing.kind == kind, Listing.status == ListingStatus.OPEN, Listing.date >= today)
        .order_by(Listing.created_at, Listing.id)
    )
    return list(db.scalars(_with_reactions(stmt)))


def my_listings(db: Session, user: User, today: date) -> list[Listing]:
    """Everything the user posted or reacted to that is still relevant."""
    reacted = select(Reaction.listing_id).where(Reaction.user_id == user.id)
    stmt = select(Listing).where(
        or_(Listing.user_id == user.id, Listing.id.in_(reacted)),
        Listing.status != ListingStatus.REMOVED,
        or_(Listing.date >= today, Listing.status == ListingStatus.TAKEN),
    )
    items = list(db.scalars(_with_reactions(stmt)))
    # Completed swaps the user isn't part of (they reacted but someone else got it) stay out.
    items = [
        listing
        for listing in items
        if listing.status == ListingStatus.OPEN
        or (deal := Deal.of(listing))
        and user.id in (deal.giver.id, deal.taker.id)
    ]
    items.sort(key=lambda listing: (listing.status == ListingStatus.TAKEN, listing.date))
    return items


def unread_count(db: Session, user: User) -> int:
    return len(
        db.scalars(
            select(Notification.id).where(
                Notification.user_id == user.id, Notification.read_at.is_(None)
            )
        ).all()
    )


# ---------------------------------------------------------------- housekeeping


def cleanup(db: Session, settings: Settings, today: date) -> None:
    """Delete what we no longer need (privacy: keep as little as possible, as short as possible)."""
    cutoff_day = today - timedelta(days=settings.retention_days)
    cutoff = utcnow() - timedelta(days=settings.retention_days)
    db.execute(delete(Listing).where(Listing.date < cutoff_day))
    db.execute(
        delete(Listing).where(Listing.status == ListingStatus.REMOVED, Listing.closed_at < cutoff)
    )
    db.execute(delete(Notification).where(Notification.created_at < cutoff))
    db.execute(delete(LoginToken).where(LoginToken.expires_at < utcnow() - timedelta(days=1)))
    db.commit()


def local_today(settings: Settings) -> date:
    return datetime.now(settings.tz).date()
