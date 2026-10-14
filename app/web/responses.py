"""Rendering pages and the POST → redirect → GET pattern."""

import hashlib
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from fastapi import BackgroundTasks, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app import mail
from app.config import get_settings
from app.models import User
from app.services import board
from app.services.errors import UserError
from app.services.transaction import queued_mails, run_write
from app.shifts import (
    DAYPARTS,
    DAYS,
    MONTHS,
    PARTS,
    SHIFT_TYPES,
    explain,
    fmt_date,
    fmt_date_long,
    fmt_stamp,
)

APP_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=APP_DIR / "templates")


def static_version() -> str:
    """Hash of all static files. Asset URLs carry it (?v=...), so they can be cached forever
    and a deploy still reaches every browser immediately."""
    digest = hashlib.sha256()
    for path in sorted((APP_DIR / "static").rglob("*")):
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()[:10]


def _stamp(dt: datetime) -> str:
    tz = get_settings().tz
    return fmt_stamp(dt.astimezone(tz), datetime.now(tz))


def _relative_day(day: date) -> str:
    """'vandaag' / 'morgen' for the date tile, '' otherwise."""
    delta = (day - get_settings().today()).days
    return {0: "vandaag", 1: "morgen"}.get(delta, "")


templates.env.globals.update(
    PARTS=PARTS,
    SHIFT_TYPES=SHIFT_TYPES,
    DAYPARTS=DAYPARTS,
    explain=explain,
    fmt_date=fmt_date,
    fmt_date_long=fmt_date_long,
    stamp=_stamp,
    relative_day=_relative_day,
    DAYS=DAYS,
    MONTHS=MONTHS,
    static_v=static_version(),
)


def flash(request: Request, text: str, kind: str = "ok") -> None:
    """A one-time message shown on the next page ("ok" or "error")."""
    request.session["flash"] = [*request.session.get("flash", []), [kind, text]]


def render(
    request: Request,
    template: str,
    *,
    db: Session | None = None,
    user: User | None = None,
    status_code: int = 200,
    **ctx,
) -> Response:
    """Render a page. With `db` and `user`, the tab-bar counts and bell are filled in too."""
    settings = get_settings()
    if settings.dev_mode:  # pick up CSS/JS edits without a restart
        ctx["static_v"] = static_version()
    ctx.update(
        request=request,
        user=user,
        settings=settings,
        theme="dark" if request.cookies.get("theme") == "dark" else "light",
        # A background prefetch (see app.js) must not use up messages meant for a real page.
        messages=[] if request.headers.get("x-prefetch") else request.session.pop("flash", []),
    )
    if user is not None and db is not None:
        ctx.setdefault("nav", board.nav_counts(db, user, settings.today()))
    return templates.TemplateResponse(request, template, ctx, status_code=status_code)


def safe_next(target: str | None, default: str) -> str:
    """Only allow redirects to our own paths (no //evil.com, no absolute URLs)."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return default


def redirect(target: str) -> RedirectResponse:
    return RedirectResponse(target, status_code=303)


def send_queued(db: Session, background: BackgroundTasks) -> None:
    """Send mails queued by the last committed transaction, after the response is out."""
    settings = get_settings()
    for m in queued_mails(db):
        background.add_task(mail.send, settings, m.to, m.subject, m.body)


def run_action(
    request: Request,
    db: Session,
    background: BackgroundTasks,
    fn: Callable,
    *args,
    ok: str | None,
    go_to: str,
    **kwargs,
) -> Response:
    """The standard POST handler body: run one state change through `run_write`, flash the
    outcome (or the rule that was broken), send queued mails, and redirect to `go_to`."""
    try:
        run_write(db, fn, *args, **kwargs)
    except UserError as e:
        flash(request, str(e), "error")
    else:
        send_queued(db, background)
        if ok:
            flash(request, ok)
    return redirect(go_to)
