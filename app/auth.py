"""Magic-link login and the session cookie.

Flow: enter email → if it is on the invite list, a one-time link is mailed → the link opens a
page with a "Log in" button → POST consumes the token. The extra click matters: mail scanners
(Outlook Safe Links, virus scanners) open every link in a mail, and a GET that logs in would burn
the token before the colleague ever clicks it.
"""

import hashlib
import secrets
from datetime import timedelta
from urllib.parse import quote, urlparse

from fastapi import Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models import LoginToken, User, utcnow
from app.services import QueuedMail


class LoginRequired(Exception):
    pass


class Forbidden(Exception):
    pass


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def normalise_email(email: str) -> str:
    return (email or "").strip().lower()


def request_login(db: Session, settings: Settings, email: str, next_path: str = "") -> str | None:
    """Create a login token and queue its mail. Returns the link (for dev mode), or None when
    the address is unknown or rate limited. The caller shows the same message either way, so
    the page doesn't reveal who is on the list."""
    user = db.scalar(select(User).where(User.email == normalise_email(email)))
    if user is None or not user.is_active:
        return None
    hour_ago = utcnow() - timedelta(hours=1)
    recent = db.scalar(
        select(func.count(LoginToken.id)).where(
            LoginToken.user_id == user.id, LoginToken.created_at > hour_ago
        )
    )
    if recent >= settings.login_mails_per_hour:
        return None

    raw = secrets.token_urlsafe(32)
    db.add(
        LoginToken(
            user_id=user.id,
            token_hash=_hash(raw),
            expires_at=utcnow() + timedelta(minutes=settings.login_link_minutes),
        )
    )
    link = f"{settings.base_url}/login/{raw}"
    if next_path:
        link += f"?next={quote(next_path, safe='/')}"
    db.info.setdefault("mails", []).append(
        QueuedMail(
            user.email,
            f"Inloggen bij {settings.app_name}",
            f"Hoi {user.first_name},\n\n"
            f"Klik op deze link om in te loggen bij {settings.app_name}:\n\n{link}\n\n"
            f"De link werkt {settings.login_link_minutes} minuten en maar één keer.\n"
            "Heb je niet geprobeerd in te loggen? Dan kun je deze mail negeren.",
        )
    )
    db.commit()
    return link


def find_token(db: Session, raw: str) -> LoginToken | None:
    token = db.scalar(select(LoginToken).where(LoginToken.token_hash == _hash(raw)))
    if token is None or token.used_at is not None or token.expires_at < utcnow():
        return None
    if not token.user.is_active:
        return None
    return token


def consume_token(db: Session, raw: str) -> User | None:
    token = find_token(db, raw)
    if token is None:
        return None
    token.used_at = utcnow()
    token.user.last_login_at = utcnow()
    db.commit()
    return token.user


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
