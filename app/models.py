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
from app.shifts import ShiftInfo


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


class ReactionStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    WITHDRAWN = "withdrawn"
    EXPIRED = "expired"  # the listing went to someone else or was removed


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Optional: people join with just a name. With an email they get mail notifications and
    # can log in with a mailed link. Only set after the address is verified.
    email: Mapped[str | None] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    email_notifications: Mapped[bool] = mapped_column(Boolean, default=True)
    # Bumped on "log out everywhere": every cookie with an older epoch stops working.
    session_epoch: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    @property
    def first_name(self) -> str:
        return self.name.split(" ")[0]


class LoginToken(Base):
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
    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[Kind] = mapped_column(String(10))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    # Offers have one shift type; wanted requests a list of acceptable types. Everything about
    # *when/where* beyond the date is optional: "HG, thursday evening" is a complete listing.
    start: Mapped[str | None] = mapped_column(String(5))
    end: Mapped[str | None] = mapped_column(String(5))
    daypart: Mapped[str | None] = mapped_column(String(10))  # only used when there's no time
    hall: Mapped[str | None] = mapped_column(String(60))  # zaal
    workplace: Mapped[str | None] = mapped_column(String(60))  # werkplek / bar
    shift_type: Mapped[str | None] = mapped_column(String(8))
    wanted_types: Mapped[str | None] = mapped_column(String(80))
    note: Mapped[str] = mapped_column(Text, default="")  # opmerking
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
    def pending_reactions(self) -> list["Reaction"]:
        return [r for r in self.reactions if r.status == ReactionStatus.PENDING]

    @property
    def accepted_reaction(self) -> "Reaction | None":
        return next((r for r in self.reactions if r.status == ReactionStatus.ACCEPTED), None)


class Reaction(Base):
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
    offer_daypart: Mapped[str | None] = mapped_column(String(10))
    offer_hall: Mapped[str | None] = mapped_column(String(60))
    offer_workplace: Mapped[str | None] = mapped_column(String(60))
    offer_type: Mapped[str | None] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    listing: Mapped[Listing] = relationship(back_populates="reactions")
    user: Mapped[User] = relationship()

    @property
    def offer_info(self) -> ShiftInfo:
        """The shift offered in reply to a wanted request (on the request's date)."""
        return ShiftInfo(
            self.offer_type or "",
            self.listing.date,
            self.offer_start,
            self.offer_end,
            self.offer_daypart,
            self.offer_hall,
            self.offer_workplace,
        )


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    link: Mapped[str] = mapped_column(String(200), default="/mijn")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class AppSetting(Base):
    """Small key/value store for settings admins change at runtime (the join code)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
