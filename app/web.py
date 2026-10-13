"""Template rendering helpers shared by all routes."""

import hashlib
from datetime import datetime
from pathlib import Path

from fastapi import BackgroundTasks, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import mail, services
from app.config import get_settings
from app.models import Kind, Listing, ListingStatus, Reaction, ReactionStatus, User
from app.shifts import DAYPARTS, PARTS, SHIFT_TYPES, explain, fmt_date, fmt_date_long, fmt_stamp

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def _static_version() -> str:
    """Hash of all static files, appended as ?v=... so a deploy busts browser caches."""
    h = hashlib.sha256()
    for f in sorted((Path(__file__).parent / "static").rglob("*")):
        if f.is_file():
            h.update(f.read_bytes())
    return h.hexdigest()[:10]


def _stamp(dt: datetime) -> str:
    tz = get_settings().tz
    return fmt_stamp(dt.astimezone(tz), datetime.now(tz))


templates.env.globals.update(
    PARTS=PARTS,
    SHIFT_TYPES=SHIFT_TYPES,
    DAYPARTS=DAYPARTS,
    explain=explain,
    fmt_date=fmt_date,
    fmt_date_long=fmt_date_long,
    stamp=_stamp,
    static_v=_static_version(),
)


def flash(request: Request, text: str, kind: str = "ok") -> None:
    request.session.setdefault("flash", [])
    request.session["flash"] = [*request.session["flash"], [kind, text]]


def render(
    request: Request,
    template: str,
    *,
    db: Session | None = None,
    user: User | None = None,
    status_code: int = 200,
    **ctx,
):
    settings = get_settings()
    if settings.dev_mode:  # pick up CSS/JS edits without a restart
        ctx["static_v"] = _static_version()
    ctx.update(
        request=request,
        user=user,
        settings=settings,
        messages=request.session.pop("flash", []),
    )
    if user is not None and db is not None:
        today = services.local_today(settings)
        counts = dict(
            db.execute(
                select(Listing.kind, func.count(Listing.id))
                .where(Listing.status == ListingStatus.OPEN, Listing.date >= today)
                .group_by(Listing.kind)
            ).all()
        )
        ctx.setdefault("n_offer", counts.get(Kind.OFFER, 0))
        ctx.setdefault("n_wanted", counts.get(Kind.WANTED, 0))
        # "Mijn ruilen" badge = reactions waiting for this user's decision.
        ctx.setdefault(
            "n_todo",
            db.scalar(
                select(func.count(Reaction.id))
                .join(Listing)
                .where(
                    Listing.user_id == user.id,
                    Listing.status == ListingStatus.OPEN,
                    Listing.date >= today,
                    Reaction.status == ReactionStatus.PENDING,
                )
            ),
        )
        ctx.setdefault("unread", services.unread_count(db, user))
    return templates.TemplateResponse(request, template, ctx, status_code=status_code)


def safe_next(target: str | None, default: str) -> str:
    """Only allow redirects to our own paths (no //evil.com, no absolute URLs)."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return default


def redirect(target: str) -> RedirectResponse:
    return RedirectResponse(target, status_code=303)


def send_queued(db: Session, background: BackgroundTasks) -> None:
    """Hand mails queued during a committed transaction to a background task, so the page
    answers immediately and a slow mail server doesn't make the click feel stuck."""
    settings = get_settings()
    for m in services.queued_mails(db):
        background.add_task(mail.send, settings, m.to, m.subject, m.body)
