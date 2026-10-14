"""Who is making the request, and is the request allowed at all.

The session is a signed cookie (Starlette's SessionMiddleware) holding the user id and their
`session_epoch`. "Log out everywhere" bumps the epoch, which invalidates every older cookie.
The cookie is renewed on each response, so active users stay logged in (SESSION_DAYS).
"""

from urllib.parse import urlparse

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models import User


class LoginRequired(Exception):
    """Raised by `require_user`; main.py turns it into a redirect to /login."""


class Forbidden(Exception):
    """Raised by `require_admin`; main.py turns it into a 403."""


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
    least Sec-Fetch-Site) with every POST, and it must be this site."""
    settings = settings or get_settings()
    if request.headers.get("sec-fetch-site") in ("cross-site", "same-site"):
        return False
    origin = request.headers.get("origin")
    if origin and origin != "null":
        ours, theirs = urlparse(settings.base_url), urlparse(origin)
        return (theirs.scheme, theirs.netloc) == (ours.scheme, ours.netloc)
    return True
