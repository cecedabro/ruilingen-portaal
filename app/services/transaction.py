"""Safe writes and the notification outbox.

Concurrency: SQLite allows one writer at a time, and in WAL mode a transaction that read old
data and then tries to write fails ("database is locked") instead of overwriting a newer
change. `run_write` therefore starts every change on a fresh transaction and simply retries
it on such a conflict. Combined with conditional UPDATEs where it matters (see
listings.accept), a shift can never be given away twice.

Outbox: services call `notify()` while they change data. The in-app notification is part of
the same transaction; the optional email is only queued on the session and sent after the
commit by the web layer (web.responses.send_queued), so a slow mail server never blocks a
click and a rolled-back change never sends mail.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Notification, User

T = TypeVar("T")
_ATTEMPTS = 4


@dataclass
class QueuedMail:
    to: str
    subject: str
    body: str


def run_write(db: Session, fn: Callable[..., T], *args, **kwargs) -> T:
    """Run `fn(db, *args, **kwargs)` in its own transaction and commit it. Retries when
    SQLite reports a write conflict; any other exception rolls back and propagates."""
    for attempt in range(_ATTEMPTS):
        db.rollback()  # end any read transaction, so we work on the latest data
        db.info["mails"] = []
        try:
            result = fn(db, *args, **kwargs)
            db.commit()
            return result
        except OperationalError as e:
            db.rollback()
            if "locked" not in str(e) or attempt == _ATTEMPTS - 1:
                raise
            time.sleep(0.05 * (attempt + 1))
        except Exception:
            db.rollback()
            raise
    raise AssertionError("unreachable")


def queue_mail(db: Session, mail: QueuedMail) -> None:
    db.info.setdefault("mails", []).append(mail)


def queued_mails(db: Session) -> list[QueuedMail]:
    """Take the mails queued during the last (committed) transaction."""
    return db.info.pop("mails", [])


def notify(db: Session, user: User, text: str, link: str = "/mijn", *, mail: bool = False) -> None:
    """In-app notification (the bell). With `mail=True` also an email, if the user verified
    an address, has mails on, and mail is configured on this server. Only "someone reacted to
    your shift" mails; everything else is bell-only, so mails stay rare and worth reading."""
    db.add(Notification(user_id=user.id, text=text, link=link))
    settings = get_settings()
    if not (mail and user.email and user.email_notifications and settings.mail_enabled):
        return
    base = settings.base_url
    body = (
        f"Hoi {user.first_name},\n\n{text}\n\n"
        f"Bekijk de reactie en bevestig of wijs af:\n{base}{link}\n\n"
        f"—\n{settings.app_name}. Deze mails uitzetten kan op {base}/account"
    )
    queue_mail(db, QueuedMail(user.email, text, body))
