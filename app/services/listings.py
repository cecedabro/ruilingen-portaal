"""The life of a listing: post it, react to it, confirm one reaction, or take it down.

    Listing:   open ──(owner confirms a reaction)──► taken
                 └───(owner or admin removes it)───► removed
    Reaction:  pending ──► accepted   (the owner chose this one)
                       ├─► declined   (the owner said no)
                       ├─► withdrawn  (the reactor changed their mind)
                       └─► expired    (another reaction was chosen, or the listing was removed)

Order matters: reactions are listed by (created_at, id), so "who was first" is unambiguous,
but the owner may choose any of them.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Kind, Listing, ListingStatus, Reaction, ReactionStatus, User, utcnow
from app.services import appdata
from app.services.errors import UserError
from app.services.transaction import notify
from app.shifts import DAYPARTS, ShiftInfo, fmt_date, is_shift_type, is_time

MAX_OPEN_LISTINGS = 30  # per person, against accidental or deliberate flooding
MAX_NOTE = 200
MAX_DAYS_AHEAD = 366


# ---------------------------------------------------------------- validation


def _check_date(day: date, today: date) -> None:
    if day < today:
        raise UserError("Die datum is al voorbij.")
    if day > today + timedelta(days=MAX_DAYS_AHEAD):
        raise UserError("Zo ver vooruit kan niet.")


def _clean_note(note: str) -> str:
    note = (note or "").strip()
    if len(note) > MAX_NOTE:
        raise UserError(f"De opmerking mag maximaal {MAX_NOTE} tekens zijn.")
    return note


def _check_capacity(db: Session, user: User, today: date) -> None:
    nth = db.scalar(
        select(Listing.id)
        .where(Listing.user_id == user.id, Listing.status == ListingStatus.OPEN)
        .where(Listing.date >= today)
        .offset(MAX_OPEN_LISTINGS - 1)
        .limit(1)
    )
    if nth is not None:
        raise UserError(f"Je hebt al {MAX_OPEN_LISTINGS} open diensten staan.")


def _pick(value: str | None, options: list[str], label: str) -> str | None:
    """Match a submitted choice against an admin list (case-insensitive); empty = None."""
    value = " ".join((value or "").split())
    if not value:
        return None
    for option in options:
        if option.lower() == value.lower():
            return option
    raise UserError(f"Kies een {label} uit de lijst.")


def shift_details(
    db: Session,
    *,
    start: str | None = None,
    end: str | None = None,
    hall: str | None = None,
    workplace: str | None = None,
) -> dict:
    """When/where of a concrete shift (one given away or offered in reply): begin and end
    time are required; zaal and werkplek are optional choices from the admin lists."""
    start, end = (start or "").strip(), (end or "").strip()
    if not (is_time(start) and is_time(end)):
        raise UserError("Vul een begin- en eindtijd in.")
    if start == end:
        raise UserError("Begin- en eindtijd zijn gelijk.")
    return {
        "start": start,
        "end": end,
        "hall": _pick(hall, appdata.get_list(db, "halls"), "zaal"),
        "workplace": _pick(workplace, appdata.get_list(db, "workplaces"), "werkplek"),
    }


# ---------------------------------------------------------------- posting


def create_offer(
    db: Session,
    user: User,
    *,
    day: date,
    code: str,
    note: str,
    today: date,
    start: str | None = None,
    end: str | None = None,
    hall: str | None = None,
    workplace: str | None = None,
) -> Listing:
    """Aangeboden: `user` gives away one concrete shift."""
    _check_date(day, today)
    if not is_shift_type(code):
        raise UserError("Kies een soort dienst.")
    details = shift_details(db, start=start, end=end, hall=hall, workplace=workplace)
    _check_capacity(db, user, today)
    listing = Listing(
        kind=Kind.OFFER, user_id=user.id, date=day, shift_type=code, note=_clean_note(note),
        **details,
    )  # fmt: skip
    db.add(listing)
    db.flush()  # assigns listing.id
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
    """Gezocht: `user` looks for a shift on `day`, of any of the given types."""
    _check_date(day, today)
    codes = [c for c in dict.fromkeys(codes) if is_shift_type(c)]
    if not codes:
        raise UserError("Kies minstens één soort dienst.")
    _check_capacity(db, user, today)
    listing = Listing(
        kind=Kind.WANTED,
        user_id=user.id,
        date=day,
        wanted_types=",".join(codes),
        daypart=daypart if daypart in DAYPARTS else None,
        note=_clean_note(note),
    )
    db.add(listing)
    db.flush()
    return listing


# ---------------------------------------------------------------- reacting


def _open_listing(db: Session, listing_id: int, today: date) -> Listing:
    listing = db.get(Listing, listing_id)
    if listing is None or listing.status == ListingStatus.REMOVED:
        raise UserError("Deze dienst bestaat niet meer.")
    if listing.status == ListingStatus.TAKEN:
        raise UserError("Deze dienst is net vergeven.")
    if listing.date < today:
        raise UserError("Deze dienst is al voorbij.")
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
    offer_hall: str | None = None,
    offer_workplace: str | None = None,
) -> Reaction:
    """ "Ik neem 'm" on an offer, or "ik heb er een" on a wanted request (with the shift you
    offer in `offer_*`). One pending reaction per person per listing (a database index)."""
    listing = _open_listing(db, listing_id, today)
    if listing.user_id == user.id:
        raise UserError("Je kunt niet op je eigen dienst reageren.")
    reaction = Reaction(listing_id=listing.id, user_id=user.id)
    if listing.kind == Kind.WANTED:
        if not (offer_type and is_shift_type(offer_type)):
            raise UserError("Kies de soort dienst die je aanbiedt.")
        details = shift_details(
            db, start=offer_start, end=offer_end, hall=offer_hall, workplace=offer_workplace
        )
        reaction.offer_type = offer_type
        for key, value in details.items():
            setattr(reaction, f"offer_{key}", value)
    db.add(reaction)
    try:
        db.flush()
    except IntegrityError:  # uq_reaction_pending: a double click or a second tab
        raise UserError("Je hebt hier al op gereageerd.") from None

    when = fmt_date(listing.date)
    if listing.kind == Kind.OFFER:
        text = f"{user.name} wil je {listing.shift_type}-dienst van {when} overnemen."
    else:
        text = f"{user.name} biedt je een {offer_type}-dienst aan op {when}."
    notify(db, listing.user, text)
    return reaction


def withdraw(db: Session, user: User, reaction_id: int) -> None:
    """The reactor takes their own pending reaction back."""
    reaction = db.get(Reaction, reaction_id)
    if reaction is None or reaction.user_id != user.id:
        raise UserError("Reactie niet gevonden.")
    if reaction.status != ReactionStatus.PENDING:
        raise UserError("Deze reactie loopt niet meer.")
    reaction.status = ReactionStatus.WITHDRAWN
    reaction.decided_at = utcnow()


def _pending_on_my_listing(db: Session, owner: User, reaction_id: int) -> Reaction:
    reaction = db.get(Reaction, reaction_id)
    if reaction is None or reaction.listing.user_id != owner.id:
        raise UserError("Reactie niet gevonden.")
    if reaction.status != ReactionStatus.PENDING:
        raise UserError("Deze reactie is ingetrokken of al afgehandeld.")
    return reaction


def decline(db: Session, owner: User, reaction_id: int) -> None:
    reaction = _pending_on_my_listing(db, owner, reaction_id)
    reaction.status = ReactionStatus.DECLINED
    reaction.decided_at = utcnow()
    when = fmt_date(reaction.listing.date)
    notify(db, reaction.user, f"{owner.name} heeft je reactie op {when} afgewezen.")


def accept(db: Session, owner: User, reaction_id: int, *, today: date) -> Listing:
    """The owner confirms one reaction: the swap is done (the "double confirmation")."""
    reaction = _pending_on_my_listing(db, owner, reaction_id)
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
        raise UserError("Deze dienst is net vergeven.")
    chosen = db.execute(
        update(Reaction)
        .where(Reaction.id == reaction.id, Reaction.status == ReactionStatus.PENDING)
        .values(status=ReactionStatus.ACCEPTED, decided_at=now)
    ).rowcount
    if chosen != 1:
        raise UserError("Deze reactie is net ingetrokken.")
    db.expire_all()  # the UPDATEs bypassed the ORM; reload what we read next

    when = fmt_date(listing.date)
    for other in listing.pending_reactions:
        other.status = ReactionStatus.EXPIRED
        other.decided_at = now
        notify(db, other.user, f"De dienst van {when} is aan iemand anders gegeven.")
    notify(
        db,
        reaction.user,
        f"{owner.name} heeft bevestigd: de ruil van {when} is rond. Mail planning vanuit Mijn.",
    )
    return listing


# ---------------------------------------------------------------- taking a listing down


def _close(db: Session, listing: Listing, reason: str) -> None:
    """Mark an open listing removed and tell everyone who was waiting on it."""
    now = utcnow()
    listing.status = ListingStatus.REMOVED
    listing.closed_at = now
    for other in listing.pending_reactions:
        other.status = ReactionStatus.EXPIRED
        other.decided_at = now
        notify(db, other.user, reason)


def remove_listing(db: Session, owner: User, listing_id: int) -> None:
    listing = db.get(Listing, listing_id)
    if listing is None or listing.user_id != owner.id:
        raise UserError("Dienst niet gevonden.")
    if listing.status != ListingStatus.OPEN:
        raise UserError("Deze dienst is al afgesloten.")
    _close(db, listing, f"{owner.name} heeft de dienst van {fmt_date(listing.date)} weggehaald.")


def admin_remove_listing(db: Session, admin: User, listing_id: int) -> None:
    """An admin takes down someone's open offer or request (misuse, mistakes)."""
    listing = db.get(Listing, listing_id)
    if listing is None or listing.status != ListingStatus.OPEN:
        raise UserError("Die dienst staat er niet (meer).")
    when = fmt_date(listing.date)
    _close(db, listing, f"De dienst van {when} is door een beheerder weggehaald.")
    if listing.user_id != admin.id:
        notify(db, listing.user, f"Een beheerder heeft je dienst van {when} weggehaald.")


# ---------------------------------------------------------------- completed swaps


@dataclass
class Deal:
    """A completed swap, seen as giver → taker, whichever of the two posted the listing."""

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
        if listing.kind == Kind.OFFER:  # the poster gives the shift away
            return cls(listing, r, listing.user, r.user, listing.info)
        return cls(listing, r, r.user, listing.user, r.offer_info)  # the reactor gives theirs

    def involves(self, user: User) -> bool:
        return user.id in (self.giver.id, self.taker.id)


def mark_mail_sent(db: Session, user: User, listing_id: int) -> None:
    """One of the two says "I mailed planning"; the other one is told."""
    listing = db.get(Listing, listing_id)
    deal = Deal.of(listing) if listing and listing.status == ListingStatus.TAKEN else None
    if deal is None or not deal.involves(user):
        raise UserError("Ruil niet gevonden.")
    if listing.mail_sent_at is None:
        listing.mail_sent_at = utcnow()
        listing.mail_sent_by_id = user.id
        other = deal.taker if user.id == deal.giver.id else deal.giver
        when = fmt_date(listing.date)
        notify(db, other, f"{user.name} heeft de ruil van {when} naar planning gemaild.")
