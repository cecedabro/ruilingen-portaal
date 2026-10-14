"""One-time links: logging in on another device, and confirming a notification address.

Both are random tokens of which only a SHA-256 hash is stored (a leaked database can't be used
to log in). They're single use and short-lived. Opening one shows a page with a button and
only the POST uses it up: chat apps and mail scanners open links to make previews, and a GET
that logs in would burn the token before the person taps it.
"""

import hashlib
import secrets
from datetime import timedelta
from urllib.parse import quote

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import LoginToken, User, utcnow
from app.services.errors import UserError
from app.services.transaction import QueuedMail, queue_mail

EMAIL_LINK_HOURS = 24


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def make_link(
    db: Session,
    settings: Settings,
    user: User,
    *,
    minutes: int | None = None,
    email: str | None = None,
    next_path: str = "",
) -> str:
    """A one-time URL. With `email` it verifies that address (/email/...), otherwise it logs
    in as `user` (/login/...)."""
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


def find_token(db: Session, raw: str) -> LoginToken | None:
    """The token if it exists, is unused, not expired, and its user still exists."""
    token = db.scalar(select(LoginToken).where(LoginToken.token_hash == _hash(raw)))
    if token is None or token.used_at is not None or token.expires_at < utcnow():
        return None
    return token if token.user.is_active else None


def consume_login(db: Session, raw: str) -> User | None:
    """Use a login link. Email-verification tokens never log in."""
    token = find_token(db, raw)
    if token is None or token.email:
        return None
    token.used_at = utcnow()
    token.user.last_login_at = utcnow()
    db.commit()
    return token.user


# ---------------------------------------------------------------- notification email


def normalise_email(email: str) -> str:
    return (email or "").strip().lower()


def request_email_change(db: Session, settings: Settings, user: User, email: str) -> str:
    """Queue a verification mail for a new address. It's only saved once confirmed."""
    email = normalise_email(email)
    if "@" not in email or "." not in email.split("@")[-1] or len(email) > 254:
        raise UserError("Dat is geen geldig e-mailadres.")
    if db.scalar(select(User.id).where(User.email == email, User.id != user.id)):
        raise UserError("Dat e-mailadres hoort al bij iemand anders.")
    recent = db.scalar(
        select(func.count(LoginToken.id)).where(
            LoginToken.user_id == user.id, LoginToken.created_at > utcnow() - timedelta(hours=1)
        )
    )
    if recent >= settings.login_mails_per_hour:
        raise UserError("Te veel mails verstuurd. Probeer het over een uur opnieuw.")
    link = make_link(db, settings, user, email=email, minutes=60 * EMAIL_LINK_HOURS)
    queue_mail(
        db,
        QueuedMail(
            email,
            f"Bevestig je e-mailadres voor {settings.app_name}",
            f"Hoi {user.first_name},\n\nKlik om dit adres voor meldingen te gebruiken:\n\n"
            f"{link}\n\nNiet zelf aangevraagd? Dan kun je deze mail negeren.",
        ),
    )
    return link


def verify_email(db: Session, raw: str) -> User | None:
    """Confirm a notification address. Deliberately does not log anyone in."""
    token = find_token(db, raw)
    if token is None or not token.email:
        return None
    token.used_at = utcnow()
    taken = db.scalar(select(User.id).where(User.email == token.email, User.id != token.user_id))
    if not taken:
        token.user.email = token.email
    db.commit()
    return None if taken else token.user
