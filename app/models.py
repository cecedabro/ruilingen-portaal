"""Database tables (SQLAlchemy 2.0 ORM). See docs/database.md for the full picture.

Conventions: times are stored in UTC (UTCDateTime) and shown in Europe/Amsterdam; statuses
are short strings (StrEnum); deleting a user cascades to everything they own.
"""

from datetime import UTC, date, datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.shifts import ShiftInfo, fmt_date

# Inside `Listing` the name `date` is the column, so annotations there need another name.
Day = date


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """Stores naive UTC in SQLite, always hands back timezone-aware UTC datetimes."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            if value.tzinfo is None:
                raise ValueError("naive datetime")
            value = value.astimezone(UTC).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=UTC) if value is not None else None


class Kind(StrEnum):
    OFFER = "offer"  # "Aangeboden": someone gives a shift away
    WANTED = "wanted"  # "Gezocht": someone is looking for a shift


class ListingStatus(StrEnum):
    OPEN = "open"
    TAKEN = "taken"
    REMOVED = "removed"


class Mode(StrEnum):
    """What the poster of an offer wants in return."""

    GIVE = "give"  # just give it away
    TRADE = "trade"  # only a swap: the reactor must offer a shift back
    BOTH = "both"  # taking it is fine, a swap proposal too


class ReactionStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    WITHDRAWN = "withdrawn"
    EXPIRED = "expired"  # the listing went to someone else or was removed


class User(Base):
    """A colleague. Joins with just a name via an invite link."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Optional, only for notification mails; set once the address is verified.
    email: Mapped[str | None] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(80))  # unique (case-insensitive), checked in code
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)  # inactive = can't log in
    email_notifications: Mapped[bool] = mapped_column(Boolean, default=True)
    # Bumped on "log out everywhere": every cookie with an older epoch stops working.
    session_epoch: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    @property
    def first_name(self) -> str:
        return self.name.split(" ")[0]


class LoginToken(Base):
    """A one-time link: log in on another device, or (with `email`) verify an address."""

    __tablename__ = "login_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Only a hash is stored: a leaked database can't be used to log in.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # Set when the link verifies a new email address instead of (only) logging in.
    email: Mapped[str | None] = mapped_column(String(254))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    user: Mapped[User] = relationship()


class Listing(Base):
    """A shift on one of the boards: given away (offer) or looked for (wanted)."""

    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[Kind] = mapped_column(String(10))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    # Offer: one shift type, begin/end time ("HH:MM", required), optional zaal/werkplek.
    # Wanted: comma-separated acceptable types and an optional dagdeel instead of a time.
    start: Mapped[str | None] = mapped_column(String(5))
    end: Mapped[str | None] = mapped_column(String(5))  # may be earlier than start: past midnight
    daypart: Mapped[str | None] = mapped_column(String(10))  # ochtend / middag / avond
    hall: Mapped[str | None] = mapped_column(String(60))  # zaal, from the admin list
    workplace: Mapped[str | None] = mapped_column(String(60))  # werkplek, from the admin list
    shift_type: Mapped[str | None] = mapped_column(String(8))
    wanted_types: Mapped[str | None] = mapped_column(String(80))  # "H,HG,G"
    note: Mapped[str] = mapped_column(Text, default="")  # opmerking
    # Offers only: give away, swap, or both; and optionally what the poster would like back.
    mode: Mapped[Mode] = mapped_column(String(5), default=Mode.GIVE, server_default="give")
    want_from: Mapped[Day | None] = mapped_column(Date)
    want_to: Mapped[Day | None] = mapped_column(Date)
    want_types: Mapped[str | None] = mapped_column(String(80))  # "H,HG"
    status: Mapped[ListingStatus] = mapped_column(String(10), default=ListingStatus.OPEN)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # Set when one of the two says "I sent the mail to planning".
    mail_sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    mail_sent_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    user: Mapped[User] = relationship(foreign_keys=[user_id])
    mail_sent_by: Mapped[User | None] = relationship(foreign_keys=[mail_sent_by_id])
    reactions: Mapped[list["Reaction"]] = relationship(
        back_populates="listing",
        foreign_keys="Reaction.listing_id",
        order_by="(Reaction.created_at, Reaction.id)",
        cascade="all, delete-orphan",
    )

    @property
    def info(self) -> ShiftInfo:
        return ShiftInfo(
            self.shift_type or "",
            self.date,
            self.start,
            self.end,
            self.daypart,
            self.hall,
            self.workplace,
        )

    @property
    def wanted_type_list(self) -> list[str]:
        return [t for t in (self.wanted_types or "").split(",") if t]

    @property
    def is_swap(self) -> bool:
        """Offers where the poster wants a shift back (swap only, or swap or give)."""
        return self.kind == Kind.OFFER and self.mode in (Mode.TRADE, Mode.BOTH)

    @property
    def want_type_list(self) -> list[str]:
        return [t for t in (self.want_types or "").split(",") if t]

    @property
    def has_wish(self) -> bool:
        return self.is_swap and bool(self.want_from or self.want_to or self.want_types)

    @property
    def want_text(self) -> str:
        """'wo 21 okt – vr 23 okt · H, HG': what the poster would like back ('' if nothing)."""
        parts = []
        if self.want_from and self.want_to:
            parts.append(f"{fmt_date(self.want_from)} – {fmt_date(self.want_to)}")
        elif self.want_from:
            parts.append(f"vanaf {fmt_date(self.want_from)}")
        elif self.want_to:
            parts.append(f"t/m {fmt_date(self.want_to)}")
        if self.want_types:
            parts.append(", ".join(self.want_type_list))
        return " · ".join(parts)

    def wish_matches(self, shift: ShiftInfo) -> bool:
        """Is a proposed shift inside what the poster asked for? True when nothing was asked.
        Proposals outside the wish are allowed; they just get a hint."""
        if not self.has_wish:
            return True
        if self.want_from and shift.day < self.want_from:
            return False
        if self.want_to and shift.day > self.want_to:
            return False
        return not self.want_types or shift.code in self.want_type_list

    @property
    def pending_reactions(self) -> list["Reaction"]:
        return [r for r in self.reactions if r.status == ReactionStatus.PENDING]

    @property
    def accepted_reaction(self) -> "Reaction | None":
        return next((r for r in self.reactions if r.status == ReactionStatus.ACCEPTED), None)


class Reaction(Base):
    """Someone responding to a listing; the owner picks one (see services/listings.py)."""

    __tablename__ = "reactions"
    __table_args__ = (
        # One open reaction per person per listing. Enforced by the database, so a double
        # click or two tabs can't create a second one.
        Index(
            "uq_reaction_pending",
            "listing_id",
            "user_id",
            unique=True,
            sqlite_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[ReactionStatus] = mapped_column(String(10), default=ReactionStatus.PENDING)
    # Only for reactions on a wanted request: the shift being offered.
    offer_start: Mapped[str | None] = mapped_column(String(5))
    offer_end: Mapped[str | None] = mapped_column(String(5))
    offer_daypart: Mapped[str | None] = mapped_column(String(10))  # legacy (0.3–0.4), unused now
    # Date of the offered shift: on a wanted request it's the request's date, on a swap
    # proposal it's chosen by the reactor. Empty on older rows (then the listing's date).
    offer_date: Mapped[Day | None] = mapped_column(Date)
    # Set when the reactor picked one of their own offered shifts: it's removed from the
    # board when this swap is confirmed.
    offer_listing_id: Mapped[int | None] = mapped_column(
        ForeignKey("listings.id", ondelete="SET NULL", name="fk_reactions_offer_listing")
    )
    offer_hall: Mapped[str | None] = mapped_column(String(60))
    offer_workplace: Mapped[str | None] = mapped_column(String(60))
    offer_type: Mapped[str | None] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    listing: Mapped[Listing] = relationship(back_populates="reactions", foreign_keys=[listing_id])
    user: Mapped[User] = relationship()

    @property
    def offer_info(self) -> ShiftInfo:
        """The shift the reactor gives in return (wanted request reply, or swap proposal)."""
        return ShiftInfo(
            self.offer_type or "",
            self.offer_date or self.listing.date,
            self.offer_start,
            self.offer_end,
            self.offer_daypart,
            self.offer_hall,
            self.offer_workplace,
        )


class Notification(Base):
    """An entry behind the bell. Deleted after RETENTION_DAYS."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    link: Mapped[str] = mapped_column(String(200), default="/mijn")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class AppSetting(Base):
    """Settings admins change at runtime: zaal/werkplek lists, the planning mail template."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class InviteLink(Base):
    """A way in. The main link (in the group chat description) has no limits; extra links can
    expire and/or have a maximum number of uses. Admin links make the newcomer an admin."""

    __tablename__ = "invite_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    label: Mapped[str] = mapped_column(String(60), default="")
    role: Mapped[str] = mapped_column(String(10), default="member")  # member / admin
    is_main: Mapped[bool] = mapped_column(Boolean, default=False)
    max_uses: Mapped[int | None] = mapped_column(Integer)
    uses: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    created_by: Mapped[User | None] = relationship()

    @property
    def status(self) -> str:
        """'actief', 'ingetrokken', 'verlopen' or 'vol'."""
        if self.revoked_at:
            return "ingetrokken"
        if self.expires_at and self.expires_at <= utcnow():
            return "verlopen"
        if self.max_uses is not None and self.uses >= self.max_uses:
            return "vol"
        return "actief"
