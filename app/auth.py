"""Who you are, with as little friction as possible, and only by invitation.

- **Invite links** are the only way in: `/join/<code>`, type your name, and this browser stays
  logged in (rolling cookie). No email, no password, no list of addresses to keep. The main
  link sits in the group chat description; admins can make extra links that expire and/or
  have a use limit, and single-use 24-hour links that make the newcomer an admin.
- **One-time login links**: "link another device" on /account, or an admin making one for a
  colleague who lost their phone. Single use, short-lived, stored hashed, and they open a page
  with a button first (mail/chat link previews must not burn them).
- **Email (optional)** is only for notifications. Verifying an address does not log in.
"""

import hashlib
import secrets
from datetime import timedelta
from urllib.parse import quote, urlparse

from fastapi import Depends, Request
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models import InviteLink, LoginToken, User, utcnow
from app.services import QueuedMail, SwapError


class LoginRequired(Exception):
    pass


class Forbidden(Exception):
    pass


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def normalise_email(email: str) -> str:
    return (email or "").strip().lower()


def clean_name(name: str) -> str:
    return " ".join((name or "").split())[:60]


# ---------------------------------------------------------------- invite links

ADMIN_LINK_HOURS = 24


def main_link(db: Session) -> InviteLink:
    """The permanent group-chat link (created on first use)."""
    link = db.scalar(
        select(InviteLink).where(InviteLink.is_main.is_(True), InviteLink.revoked_at.is_(None))
    )
    if link is None:
        link = InviteLink(code=secrets.token_urlsafe(9), label="Groepsapp", is_main=True)
        db.add(link)
        db.commit()
    return link


def renew_main_link(db: Session, admin: User) -> InviteLink:
    """New code for the group-chat link; the old one stops working immediately."""
    old = main_link(db)
    old.revoked_at = utcnow()
    new = InviteLink(
        code=secrets.token_urlsafe(9), label="Groepsapp", is_main=True, created_by_id=admin.id
    )
    db.add(new)
    db.commit()
    return new


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
        # A leaked admin link must not hand out admin rights: always one person, one day.
        max_uses, expires = 1, utcnow() + timedelta(hours=ADMIN_LINK_HOURS)
    else:
        role = "member"
        if max_uses is not None and not 1 <= max_uses <= 500:
            raise SwapError("Aantal keer gebruiken moet tussen 1 en 500 liggen.")
        if valid_days is not None and not 1 <= valid_days <= 366:
            raise SwapError("Geldigheid moet tussen 1 en 366 dagen liggen.")
        expires = utcnow() + timedelta(days=valid_days) if valid_days else None
    link = InviteLink(
        code=secrets.token_urlsafe(9),
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
        raise SwapError("Die link kan niet worden ingetrokken.")
    if link.revoked_at is None:
        link.revoked_at = utcnow()
        db.commit()


def link_url(settings: Settings, link: InviteLink) -> str:
    return f"{settings.base_url}/join/{link.code}"


def usable_link(db: Session, code: str) -> InviteLink | None:
    link = db.scalar(select(InviteLink).where(InviteLink.code == code))
    return link if link is not None and link.status == "actief" else None


def check_name(db: Session, name: str, exclude_id: int | None = None) -> str:
    """Names are how colleagues recognise each other, so they must be unique."""
    name = clean_name(name)
    if len(name) < 2:
        raise SwapError("Vul je naam in.")
    stmt = select(User.id).where(func.lower(User.name) == name.lower())
    if exclude_id is not None:
        stmt = stmt.where(User.id != exclude_id)
    if db.scalar(stmt) is not None:
        raise SwapError(
            "Die naam is al in gebruik. Ben jij dat op een ander apparaat? "
            "Koppel dit apparaat via Account op je andere apparaat, of vraag een beheerder."
        )
    return name


def join(db: Session, code: str, name: str) -> User:
    link = usable_link(db, code)
    if link is None:
        raise SwapError("Deze link werkt niet meer. Vraag een nieuwe link in de groep.")
    user = User(name=check_name(db, name), is_admin=link.role == "admin")
    # Count the use atomically, so a link with 1 use left can't let two people in at once.
    taken = db.execute(
        update(InviteLink)
        .where(InviteLink.id == link.id, InviteLink.revoked_at.is_(None))
        .where(or_(InviteLink.max_uses.is_(None), InviteLink.uses < InviteLink.max_uses))
        .values(uses=InviteLink.uses + 1)
    ).rowcount
    if taken != 1:
        db.rollback()
        raise SwapError("Deze link is net vol geraakt. Vraag een nieuwe link.")
    db.add(user)
    db.commit()
    return user


# ---------------------------------------------------------------- one-time links


def make_link(
    db: Session,
    settings: Settings,
    user: User,
    *,
    minutes: int | None = None,
    email: str | None = None,
    next_path: str = "",
) -> str:
    raw = secrets.token_urlsafe(32)
    db.add(
        LoginToken(
            user_id=user.id,
            token_hash=_hash(raw),
            email=email,
            expires_at=utcnow() + timedelta(minutes=minutes or settings.login_link_minutes),
        )
    )
    db.commit()
    link = f"{settings.base_url}/{'email' if email else 'login'}/{raw}"
    if next_path:
        link += f"?next={quote(next_path, safe='/')}"
    return link


def _recent_mails(db: Session, user: User) -> int:
    return db.scalar(
        select(func.count(LoginToken.id)).where(
            LoginToken.user_id == user.id, LoginToken.created_at > utcnow() - timedelta(hours=1)
        )
    )


def request_email_change(db: Session, settings: Settings, user: User, email: str) -> str:
    """Mail a verification link to a new address; it's only saved once the link is used."""
    email = normalise_email(email)
    if "@" not in email or "." not in email.split("@")[-1] or len(email) > 254:
        raise SwapError("Dat is geen geldig e-mailadres.")
    if db.scalar(select(User.id).where(User.email == email, User.id != user.id)):
        raise SwapError("Dat e-mailadres hoort al bij iemand anders.")
    if _recent_mails(db, user) >= settings.login_mails_per_hour:
        raise SwapError("Te veel mails verstuurd. Probeer het over een uur opnieuw.")
    link = make_link(db, settings, user, email=email, minutes=60 * 24)
    db.info.setdefault("mails", []).append(
        QueuedMail(
            email,
            f"Bevestig je e-mailadres voor {settings.app_name}",
            f"Hoi {user.first_name},\n\nKlik om dit adres aan je account te koppelen:\n\n{link}\n\n"
            "Niet zelf aangevraagd? Dan kun je deze mail negeren.",
        )
    )
    return link


def find_token(db: Session, raw: str) -> LoginToken | None:
    token = db.scalar(select(LoginToken).where(LoginToken.token_hash == _hash(raw)))
    if token is None or token.used_at is not None or token.expires_at < utcnow():
        return None
    if not token.user.is_active:
        return None
    return token


def consume_token(db: Session, raw: str) -> User | None:
    """Use a one-time login link (another device, or made by an admin)."""
    token = find_token(db, raw)
    if token is None or token.email:
        return None
    token.used_at = utcnow()
    token.user.last_login_at = utcnow()
    db.commit()
    return token.user


def verify_email(db: Session, raw: str) -> User | None:
    """Confirm a notification address. Deliberately does NOT log anyone in."""
    token = find_token(db, raw)
    if token is None or not token.email:
        return None
    token.used_at = utcnow()
    taken = db.scalar(select(User.id).where(User.email == token.email, User.id != token.user_id))
    if not taken:
        token.user.email = token.email
    db.commit()
    return None if taken else token.user


# ---------------------------------------------------------------- session


def log_in(request: Request, user: User) -> None:
    request.session.clear()
    request.session.update({"uid": user.id, "ep": user.session_epoch})


def log_out(request: Request) -> None:
    request.session.clear()


def current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    uid = request.session.get("uid")
    if uid is None:
        return None
    user = db.get(User, uid)
    if user is None or not user.is_active or user.session_epoch != request.session.get("ep"):
        request.session.clear()
        return None
    return user


def require_user(user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise LoginRequired
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if not user.is_admin:
        raise Forbidden
    return user


def same_origin(request: Request, settings: Settings | None = None) -> bool:
    """CSRF guard for POSTs, on top of the SameSite=Lax cookie: browsers send Origin (or at
    least Sec-Fetch-Site) on every POST, and it must be our own site."""
    settings = settings or get_settings()
    if request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}:
        return False
    origin = request.headers.get("origin")
    if origin and origin != "null":
        ours = urlparse(settings.base_url)
        theirs = urlparse(origin)
        return (theirs.scheme, theirs.netloc) == (ours.scheme, ours.netloc)
    return True
