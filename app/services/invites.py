"""Invite links: the only way to join.

- The **main link** sits in the group chat description. It never expires and has no use
  limit; admins can renew it (the old code stops working) if it ends up in the wrong place.
- **Extra links** are made by admins, optionally with an expiry and/or a maximum number of
  uses, and can be revoked.
- **Admin links** make the newcomer an admin. They are always single-use and valid for 24 hours,
  so a leaked admin link can't hand out admin rights to strangers.
"""

import secrets
from datetime import timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import InviteLink, User, utcnow
from app.services.errors import UserError
from app.services.members import check_name, clean_name

ADMIN_LINK_HOURS = 24
MAX_USES_LIMIT = 500
MAX_VALID_DAYS = 366
MAIN_LABEL = "Groepsapp"


def _new_code() -> str:
    return secrets.token_urlsafe(9)  # 12 characters, ~72 bits: not guessable


def url(settings: Settings, link: InviteLink) -> str:
    return f"{settings.base_url}/join/{link.code}"


def main_link(db: Session) -> InviteLink:
    """The current group-chat link (created on first use)."""
    link = db.scalar(
        select(InviteLink).where(InviteLink.is_main.is_(True), InviteLink.revoked_at.is_(None))
    )
    if link is None:
        link = InviteLink(code=_new_code(), label=MAIN_LABEL, is_main=True)
        db.add(link)
        db.commit()
    return link


def renew_main_link(db: Session, admin: User) -> InviteLink:
    """Replace the group-chat link; the old code stops working immediately."""
    main_link(db).revoked_at = utcnow()
    new = InviteLink(code=_new_code(), label=MAIN_LABEL, is_main=True, created_by_id=admin.id)
    db.add(new)
    db.commit()
    return new


def extra_links(db: Session, limit: int = 50) -> list[InviteLink]:
    return list(
        db.scalars(
            select(InviteLink)
            .where(InviteLink.is_main.is_(False))
            .order_by(InviteLink.created_at.desc())
            .limit(limit)
        )
    )


def create_link(
    db: Session,
    admin: User,
    *,
    label: str,
    role: str,
    max_uses: int | None,
    valid_days: int | None,
) -> InviteLink:
    if role == "admin":
        max_uses, expires = 1, utcnow() + timedelta(hours=ADMIN_LINK_HOURS)  # never negotiable
    else:
        role = "member"
        if max_uses is not None and not 1 <= max_uses <= MAX_USES_LIMIT:
            raise UserError(f"Aantal keer gebruiken moet tussen 1 en {MAX_USES_LIMIT} liggen.")
        if valid_days is not None and not 1 <= valid_days <= MAX_VALID_DAYS:
            raise UserError(f"Geldigheid moet tussen 1 en {MAX_VALID_DAYS} dagen liggen.")
        expires = utcnow() + timedelta(days=valid_days) if valid_days else None
    link = InviteLink(
        code=_new_code(),
        label=clean_name(label) or ("Beheerder" if role == "admin" else "Uitnodiging"),
        role=role,
        max_uses=max_uses,
        expires_at=expires,
        created_by_id=admin.id,
    )
    db.add(link)
    db.commit()
    return link


def revoke_link(db: Session, link_id: int) -> None:
    link = db.get(InviteLink, link_id)
    if link is None or link.is_main:
        raise UserError("Die link kan niet worden ingetrokken.")
    if link.revoked_at is None:
        link.revoked_at = utcnow()
        db.commit()


def usable_link(db: Session, code: str) -> InviteLink | None:
    link = db.scalar(select(InviteLink).where(InviteLink.code == code))
    return link if link is not None and link.status == "actief" else None


def join(db: Session, code: str, name: str) -> User:
    """Create an account through an invite link. Only a (unique) name is asked."""
    link = usable_link(db, code)
    if link is None:
        raise UserError("Deze link werkt niet meer. Vraag een nieuwe link in de groep.")
    user = User(name=check_name(db, name), is_admin=link.role == "admin")
    # Count the use with a conditional UPDATE, so a link with one use left can't let two
    # people in at the same moment.
    counted = db.execute(
        update(InviteLink)
        .where(InviteLink.id == link.id, InviteLink.revoked_at.is_(None))
        .where(or_(InviteLink.max_uses.is_(None), InviteLink.uses < InviteLink.max_uses))
        .values(uses=InviteLink.uses + 1)
    ).rowcount
    if counted != 1:
        db.rollback()
        raise UserError("Deze link is net vol geraakt. Vraag een nieuwe link.")
    db.add(user)
    db.commit()
    return user
