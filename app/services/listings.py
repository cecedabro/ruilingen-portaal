"""The life of a listing: post it, react to it, confirm one reaction, or take it down.

    Listing:   open ──(owner confirms a reaction)──► taken
                 └───(owner or admin removes it)───► removed
    Reaction:  pending ──► accepted   (the owner chose this one)
                       ├─► declined   (the owner said no)
                       ├─► withdrawn  (the reactor changed their mind)
                       └─► expired    (another reaction was chosen, or the listing was removed)

Order matters: reactions are listed by (created_at, id), so "who was first" is unambiguous,
but the owner may choose any of them.

Swaps (ruilen): an offer has a `mode`. "give": anyone can take it. "trade": a reaction must
carry a shift the reactor gives back. "both": either. The returned shift is typed in or picked
from the reactor's own open offers; in that case that offer is removed when the swap is
confirmed. A proposal outside the poster's stated wish is allowed (the poster sees a hint).
"""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Kind, Listing, ListingStatus, Mode, Reaction, ReactionStatus, User, utcnow
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


def _parse_day(value: str, label: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise UserError(f"{label}: kies een geldige datum.") from None


def _wish(mode: str, want_from: str, want_to: str, want_types: list[str]) -> dict:
    """The swap settings of an offer: mode, and optionally what the poster wants back.
    Without a swap there is no wish, whatever the form contained."""
    if mode not in (Mode.TRADE, Mode.BOTH):
        return {"mode": Mode.GIVE, "want_from": None, "want_to": None, "want_types": None}
    start, end = _parse_day(want_from, "Van"), _parse_day(want_to, "Tot")
    if start and end and end < start:
        raise UserError("De einddatum van je wens ligt voor de begindatum.")
    types = [t for t in dict.fromkeys(want_types) if is_shift_type(t)]
    return {
        "mode": Mode(mode),
        "want_from": start,
        "want_to": end,
        "want_types": ",".join(types) or None,
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
    mode: str = Mode.GIVE,
    want_from: str = "",
    want_to: str = "",
    want_types: list[str] | None = None,
) -> Listing:
    """Aangeboden: `user` gives away (or swaps) one concrete shift."""
    _check_date(day, today)
    if not is_shift_type(code):
        raise UserError("Kies een soort dienst.")
    details = shift_details(db, start=start, end=end, hall=hall, workplace=workplace)
    wish = _wish(mode, want_from, want_to, want_types or [])
    _check_capacity(db, user, today)
    listing = Listing(
        kind=Kind.OFFER,
        user_id=user.id,
        date=day,
        shift_type=code,
        note=_clean_note(note),
        **details,
        **wish,
    )
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


def _return_shift(
    db: Session,
    user: User,
    listing: Listing,
    *,
    today: date,
    offer_type: str | None,
    offer_date: str | None,
    offer_start: str | None,
    offer_end: str | None,
    offer_hall: str | None,
    offer_workplace: str | None,
    offer_listing_id: int | None,
) -> dict:
    """The shift the reactor gives back, as Reaction fields: picked from their own open
    offers, or typed in. (On a wanted request it's always on the request's date.)"""
    if offer_listing_id:
        own = db.get(Listing, offer_listing_id)
        if (
            own is None
            or own.user_id != user.id
            or own.kind != Kind.OFFER
            or own.status != ListingStatus.OPEN
            or own.id == listing.id
        ):
            raise UserError("Kies een van je eigen aangeboden diensten.")
        if listing.kind == Kind.WANTED and own.date != listing.date:
            raise UserError("Dit verzoek is voor één dag: kies een dienst van die dag.")
        return {
            "offer_listing_id": own.id,
            "offer_type": own.shift_type,
            "offer_date": own.date,
            "offer_start": own.start,
            "offer_end": own.end,
            "offer_hall": own.hall,
            "offer_workplace": own.workplace,
        }
    if not (offer_type and is_shift_type(offer_type)):
        raise UserError("Kies de soort dienst die je teruggeeft.")
    if listing.kind == Kind.WANTED:
        day = listing.date
    else:
        day = _parse_day(offer_date or "", "Datum")
        if day is None:
            raise UserError("Kies de datum van de dienst die je teruggeeft.")
        _check_date(day, today)
    details = shift_details(
        db, start=offer_start, end=offer_end, hall=offer_hall, workplace=offer_workplace
    )
    return {
        "offer_type": offer_type,
        "offer_date": day,
        **{f"offer_{key}": value for key, value in details.items()},
    }


def react(
    db: Session,
    user: User,
    listing_id: int,
    *,
    today: date,
    offer_type: str | None = None,
    offer_date: str | None = None,
    offer_start: str | None = None,
    offer_end: str | None = None,
    offer_hall: str | None = None,
    offer_workplace: str | None = None,
    offer_listing_id: int | None = None,
) -> Reaction:
    """ "Overnemen" on an offer, "ik heb er een" on a wanted request, or "ruil voorstellen" on
    a swap offer (both with the shift you give back in `offer_*`). One pending reaction per
    person per listing (a database index)."""
    listing = _open_listing(db, listing_id, today)
    if listing.user_id == user.id:
        raise UserError("Je kunt niet op je eigen dienst reageren.")

    gives_back = bool(offer_type or offer_listing_id or offer_start or offer_end)
    must_give_back = listing.kind == Kind.WANTED or listing.mode == Mode.TRADE
    may_give_back = listing.kind == Kind.OFFER and listing.mode == Mode.BOTH
    reaction = Reaction(listing_id=listing.id, user_id=user.id)
    if must_give_back or (may_give_back and gives_back):
        returned = _return_shift(
            db,
            user,
            listing,
            today=today,
            offer_type=offer_type,
            offer_date=offer_date,
            offer_start=offer_start,
            offer_end=offer_end,
            offer_hall=offer_hall,
            offer_workplace=offer_workplace,
            offer_listing_id=offer_listing_id,
        )
        for key, value in returned.items():
            setattr(reaction, key, value)
    db.add(reaction)
    try:
        db.flush()
    except IntegrityError:  # uq_reaction_pending: a double click or a second tab
        raise UserError("Je hebt hier al op gereageerd.") from None

    when = fmt_date(listing.date)
    if listing.kind == Kind.WANTED:
        text = f"{user.name} biedt je een {reaction.offer_type}-dienst aan op {when}."
    elif reaction.offer_type:
        text = (
            f"{user.name} stelt een ruil voor: je {listing.shift_type}-dienst van {when} "
            f"tegen een {reaction.offer_type}-dienst op {fmt_date(reaction.offer_date)}."
        )
    else:
        text = f"{user.name} wil je {listing.shift_type}-dienst van {when} overnemen."
    notify(db, listing.user, text, f"/mijn#l{listing.id}", mail=True)
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
    # A shift the reactor picked from their own offers is now used in this swap: take it down.
    picked = db.get(Listing, reaction.offer_listing_id) if reaction.offer_listing_id else None
    if picked is not None and picked.status == ListingStatus.OPEN:
        _close(db, picked, f"De dienst van {fmt_date(picked.date)} is geruild.")
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
    """A completed swap, seen as giver → taker, whichever of the two posted the listing.
    For a real swap (ruil) `return_shift` is what the taker gives back to the giver."""

    listing: Listing
    reaction: Reaction
    giver: User
    taker: User
    shift: ShiftInfo
    return_shift: ShiftInfo | None = None

    @classmethod
    def of(cls, listing: Listing) -> "Deal | None":
        r = listing.accepted_reaction
        if r is None:
            return None
        if listing.kind == Kind.OFFER:  # the poster gives the shift away (and maybe gets one)
            back = r.offer_info if r.offer_type else None
            return cls(listing, r, listing.user, r.user, listing.info, back)
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
