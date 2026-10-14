"""The pages you browse: the two boards, "Mijn" and notifications."""

from dataclasses import replace

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Kind, Notification, User, utcnow
from app.services import appdata, board, planning
from app.services.listings import Deal
from app.web.responses import render
from app.web.session import require_user

router = APIRouter()


def _board(request: Request, db: Session, user: User, kind: Kind):
    settings = get_settings()
    today = settings.today()
    q = request.query_params
    flt = board.BoardFilter.parse(
        q.get("soort", ""),
        q.get("dagdeel", ""),
        q.get("zaal", ""),
        q.get("vrij", ""),
        q.getlist("dag"),
    )
    everything = board.open_listings(db, kind, today)
    ranks = board.posting_ranks(everything)
    posted_order = q.get("volgorde") == "geplaatst"
    ordered = sorted(everything, key=lambda lst: ranks[lst.id]) if posted_order else everything
    return render(
        request,
        "board.html",
        db=db,
        user=user,
        tab=kind.value,
        kind=kind,
        items=flt.apply(ordered),
        total=len(everything),
        ranks=ranks,
        flt=flt,
        posted_order=posted_order,
        weeks=board.day_choices(today, everything, flt.dagen, settings.roster_release_weekday),
        halls=appdata.get_list(db, "halls"),
        workplaces=appdata.get_list(db, "workplaces"),
        here=request.url.path + (f"?{request.url.query}" if request.url.query else ""),
    )


@router.get("/aangeboden", response_class=HTMLResponse)
def offers(request: Request, user=Depends(require_user), db=Depends(get_db)):
    return _board(request, db, user, Kind.OFFER)


@router.get("/gezocht", response_class=HTMLResponse)
def wanted(request: Request, user=Depends(require_user), db=Depends(get_db)):
    return _board(request, db, user, Kind.WANTED)


@router.get("/mijn", response_class=HTMLResponse)
def mine(request: Request, user=Depends(require_user), db=Depends(get_db)):
    """Your open listings (with reactions to confirm), your reactions, and completed swaps
    with the ready-made email to planning."""
    settings = get_settings()
    items = []
    for listing in board.my_listings(db, user, settings.today()):
        deal = Deal.of(listing)
        mail = planning.compose(db, settings, deal) if deal else None
        items.append((listing, deal, mail))
    return render(request, "mine.html", db=db, user=user, tab="mijn", items=items)


@router.get("/meldingen", response_class=HTMLResponse)
def notifications(request: Request, user=Depends(require_user), db=Depends(get_db)):
    """Shows the latest notifications and marks them read (so never prefetch this page)."""
    items = list(
        db.scalars(
            select(Notification)
            .where(Notification.user_id == user.id)
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(100)
        )
    )
    unread_ids = {n.id for n in items if n.read_at is None}
    # Opening this page marks everything read, so the bell shows 0 right away.
    nav = replace(board.nav_counts(db, user, get_settings().today()), unread=0)
    response = render(
        request,
        "notifications.html",
        db=db,
        user=user,
        nav=nav,
        items=items,
        unread_ids=unread_ids,
    )
    if unread_ids:
        db.execute(
            update(Notification)
            .where(Notification.user_id == user.id, Notification.read_at.is_(None))
            .values(read_at=utcnow())
        )
        db.commit()
    return response
