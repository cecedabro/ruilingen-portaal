"""Delete what we no longer need: keep as little as possible, for as short as possible."""

from datetime import date, datetime, timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Listing, ListingStatus, LoginToken, Notification, User, utcnow


def cleanup(db: Session, settings: Settings, today: date) -> None:
    """Runs every few hours (see main.py). Reactions go with their listing (cascade)."""
    keep = timedelta(days=settings.retention_days)
    db.execute(delete(Listing).where(Listing.date < today - keep))
    db.execute(
        delete(Listing).where(
            Listing.status == ListingStatus.REMOVED, Listing.closed_at < utcnow() - keep
        )
    )
    db.execute(delete(Notification).where(Notification.created_at < utcnow() - keep))
    # Notifications about a shift day that's over.
    db.execute(delete(Notification).where(Notification.about_date < today))
    # Read notifications, after each user's "Gelezen meldingen wissen na" preference.
    for days in set(db.scalars(select(User.keep_read_days).distinct())) - {None}:
        db.execute(
            delete(Notification).where(
                Notification.read_at < utcnow() - timedelta(days=days),
                Notification.user_id.in_(select(User.id).where(User.keep_read_days == days)),
            )
        )
    db.execute(delete(LoginToken).where(LoginToken.expires_at < utcnow() - timedelta(days=1)))
    db.commit()


def clear_old_notifications(db: Session, user: User, now: datetime) -> None:
    """The same rules for one user, when they open the bell (the caller commits)."""
    stale = [Notification.about_date < now.date()]
    if user.keep_read_days is not None:
        stale.append(Notification.read_at < utcnow() - timedelta(days=user.keep_read_days))
    db.execute(delete(Notification).where(Notification.user_id == user.id, or_(*stale)))
