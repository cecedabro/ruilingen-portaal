"""Who you are, with as little friction as possible.

- **Join link** (the normal way in): `/join/<code>` is shared in the group chat. Open it, type
  your name, and this browser stays logged in (rolling cookie). No email, no password. The code
  keeps strangers off the public site; admins can rotate it.
- **One-time links**: "link another device" on /account, or an admin making one for a colleague
  who lost their phone. Single use, short-lived, stored hashed.
- **Email (optional)**: with a verified address you get mail notifications and can log in with a
  mailed link. Such links open a page with a button first: mail scanners open every link in a
  mail, and a GET that logs in would burn the token before the colleague clicks it.
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
from app.models import AppSetting, LoginToken, User, utcnow
from app.services import QueuedMail, SwapError

JOIN_CODE_KEY = "join_code"


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


# ---------------------------------------------------------------- join link


def join_code(db: Session) -> str:
    row = db.get(AppSetting, JOIN_CODE_KEY)
    if row is None:
        row = AppSetting(key=JOIN_CODE_KEY, value=secrets.token_urlsafe(9))
        db.add(row)
        db.commit()
    return row.value


def rotate_join_code(db: Session) -> str:
    row = db.get(AppSetting, JOIN_CODE_KEY)
    code = secrets.token_urlsafe(9)
    if row is None:
        db.add(AppSetting(key=JOIN_CODE_KEY, value=code))
    else:
        row.value = code
    db.commit()
    return code


def join_link(db: Session, settings: Settings) -> str:
    return f"{settings.base_url}/join/{join_code(db)}"


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
    if not secrets.compare_digest(code, join_code(db)):
        raise SwapError("Deze link werkt niet meer. Vraag de nieuwe link in de groep.")
    user = User(name=check_name(db, name))
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
    link = f"{settings.base_url}/login/{raw}"
    if next_path:
        link += f"?next={quote(next_path, safe='/')}"
    return link


def _recent_mails(db: Session, user: User) -> int:
    return db.scalar(
        select(func.count(LoginToken.id)).where(
            LoginToken.user_id == user.id, LoginToken.created_at > utcnow() - timedelta(hours=1)
        )
    )


def request_login(db: Session, settings: Settings, email: str, next_path: str = "") -> str | None:
    """Mail a login link. Returns the link (for dev mode), or None when the address is unknown
    or rate limited. The caller shows the same message either way, so the page doesn't reveal
    who has an account."""
    user = db.scalar(select(User).where(User.email == normalise_email(email)))
    if user is None or not user.is_active or not settings.mail_enabled:
        return None
    if _recent_mails(db, user) >= settings.login_mails_per_hour:
        return None
    link = make_link(db, settings, user, next_path=next_path)
    db.info.setdefault("mails", []).append(
        QueuedMail(
            user.email,
            f"Inloggen bij {settings.app_name}",
            f"Hoi {user.first_name},\n\nKlik om in te loggen:\n\n{link}\n\n"
            f"De link werkt {settings.login_link_minutes} minuten en één keer.\n"
            "Niet zelf aangevraagd? Dan kun je deze mail negeren.",
        )
    )
    return link


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
    token = find_token(db, raw)
    if token is None:
        return None
    token.used_at = utcnow()
    user = token.user
    user.last_login_at = utcnow()
    if token.email and not db.scalar(
        select(User.id).where(User.email == token.email, User.id != user.id)
    ):
        user.email = token.email
    db.commit()
    return user


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
