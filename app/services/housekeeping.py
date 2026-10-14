"""Delete what we no longer need: keep as little as possible, for as short as possible."""

from datetime import date, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Listing, ListingStatus, LoginToken, Notification, utcnow


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
    db.execute(delete(LoginToken).where(LoginToken.expires_at < utcnow() - timedelta(days=1)))
    db.commit()
