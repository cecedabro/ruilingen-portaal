"""Members: names, the admin role, and deleting accounts."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Listing, ListingStatus, User
from app.services.errors import UserError
from app.services.listings import remove_listing

MAX_NAME = 60


def clean_name(name: str) -> str:
    return " ".join((name or "").split())[:MAX_NAME]


def check_name(db: Session, name: str, exclude_id: int | None = None) -> str:
    """Names are how colleagues recognise each other, so they must be unique."""
    name = clean_name(name)
    if len(name) < 2:
        raise UserError("Vul je naam in.")
    stmt = select(User.id).where(func.lower(User.name) == name.lower())
    if exclude_id is not None:
        stmt = stmt.where(User.id != exclude_id)
    if db.scalar(stmt) is not None:
        raise UserError(
            "Die naam is al in gebruik. Ben jij dat op een ander apparaat? "
            "Koppel dit apparaat via Account op je andere apparaat, of vraag een beheerder."
        )
    return name


def all_members(db: Session) -> list[User]:
    """Admins first, then by name."""
    return list(db.scalars(select(User).order_by(User.is_admin.desc(), func.lower(User.name))))


def _admin_count(db: Session) -> int:
    return db.scalar(select(func.count(User.id)).where(User.is_admin.is_(True)))


def set_admin(db: Session, target: User, make_admin: bool) -> None:
    """There must always be at least one admin, or nobody could manage the app."""
    if not make_admin and target.is_admin and _admin_count(db) <= 1:
        raise UserError("Dit is de enige beheerder; die kan geen gewoon lid worden.")
    target.is_admin = make_admin


def delete_user(db: Session, target: User) -> None:
    """Delete an account and everything of it (listings, reactions, notifications, tokens,
    via ON DELETE CASCADE). Open listings are closed first so whoever reacted is told."""
    if target.is_admin and _admin_count(db) <= 1:
        raise UserError("Dit is de enige beheerder. Maak eerst iemand anders beheerder.")
    for listing in db.scalars(select(Listing).where(Listing.user_id == target.id)):
        if listing.status == ListingStatus.OPEN:
            remove_listing(db, target, listing.id)
    db.flush()
    db.delete(target)
