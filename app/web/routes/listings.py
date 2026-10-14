"""Posting a listing and every action on listings and reactions. All POST → redirect."""

from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Kind, User
from app.services import appdata, listings
from app.services.errors import UserError
from app.services.transaction import run_write
from app.web.responses import flash, redirect, render, run_action, safe_next
from app.web.session import require_user

router = APIRouter()


def _today() -> date:
    return get_settings().today()


# ---------------------------------------------------------------- posting


def _post_page(request: Request, db: Session, user: User, kind: Kind, form: dict, **ctx):
    return render(
        request,
        "post.html",
        db=db,
        user=user,
        tab="plaatsen",
        kind=kind,
        today=_today(),
        form=form,
        halls=appdata.get_list(db, "halls"),
        workplaces=appdata.get_list(db, "workplaces"),
        **ctx,
    )


@router.get("/plaatsen", response_class=HTMLResponse)
def post_form(
    request: Request, soort: str = "aanbod", user=Depends(require_user), db=Depends(get_db)
):
    kind = Kind.WANTED if soort == "gezocht" else Kind.OFFER
    return _post_page(request, db, user, kind, form={})


@router.post("/plaatsen", response_class=HTMLResponse)
def post_submit(
    request: Request,
    kind: Kind = Form(...),
    day: str = Form(""),
    code: str = Form(""),  # offer: one type
    codes: list[str] = Form([]),  # wanted: acceptable types
    start: str = Form(""),
    end: str = Form(""),
    daypart: str = Form(""),  # wanted only
    hall: str = Form(""),
    workplace: str = Form(""),
    note: str = Form(""),
    user=Depends(require_user),
    db=Depends(get_db),
):
    form = dict(
        day=day,
        code=code,
        codes=codes,
        start=start,
        end=end,
        daypart=daypart,
        hall=hall,
        workplace=workplace,
        note=note,
    )
    try:
        try:
            parsed_day = date.fromisoformat(day)
        except ValueError:
            raise UserError("Kies een datum.") from None
        if kind == Kind.OFFER:
            listing = run_write(
                db,
                listings.create_offer,
                user,
                day=parsed_day,
                code=code,
                note=note,
                today=_today(),
                start=start,
                end=end,
                hall=hall,
                workplace=workplace,
            )
        else:
            listing = run_write(
                db,
                listings.create_wanted,
                user,
                day=parsed_day,
                codes=codes,
                note=note,
                today=_today(),
                daypart=daypart,
            )
    except UserError as e:  # show the form again, filled in, with the problem on top
        return _post_page(request, db, user, kind, form, error=str(e), status_code=422)
    flash(request, "Geplaatst.")
    board = "/aangeboden" if kind == Kind.OFFER else "/gezocht"
    return redirect(f"{board}#l{listing.id}")


# ---------------------------------------------------------------- reacting


@router.post("/listings/{listing_id}/react")
def react(
    request: Request,
    background: BackgroundTasks,
    listing_id: int,
    next: str = Form(""),
    offer_type: str | None = Form(None),  # only for a wanted request: the shift you offer
    offer_start: str | None = Form(None),
    offer_end: str | None = Form(None),
    offer_hall: str | None = Form(None),
    offer_workplace: str | None = Form(None),
    user=Depends(require_user),
    db=Depends(get_db),
):
    return run_action(
        request,
        db,
        background,
        listings.react,
        user,
        listing_id,
        today=_today(),
        offer_type=offer_type,
        offer_start=offer_start,
        offer_end=offer_end,
        offer_hall=offer_hall,
        offer_workplace=offer_workplace,
        ok="Gereageerd.",
        go_to=safe_next(next, "/aangeboden") + f"#l{listing_id}",
    )


@router.post("/reactions/{reaction_id}/withdraw")
def withdraw(
    request: Request,
    background: BackgroundTasks,
    reaction_id: int,
    next: str = Form(""),
    user=Depends(require_user),
    db=Depends(get_db),
):
    return run_action(
        request,
        db,
        background,
        listings.withdraw,
        user,
        reaction_id,
        ok="Ingetrokken.",
        go_to=safe_next(next, "/mijn"),
    )


# ---------------------------------------------------------------- the owner decides


@router.post("/reactions/{reaction_id}/accept")
def accept(
    request: Request,
    background: BackgroundTasks,
    reaction_id: int,
    user=Depends(require_user),
    db=Depends(get_db),
):
    return run_action(
        request,
        db,
        background,
        listings.accept,
        user,
        reaction_id,
        today=_today(),
        ok="Rond! Mail nu planning.",
        go_to="/mijn",
    )


@router.post("/reactions/{reaction_id}/decline")
def decline(
    request: Request,
    background: BackgroundTasks,
    reaction_id: int,
    user=Depends(require_user),
    db=Depends(get_db),
):
    return run_action(
        request, db, background, listings.decline, user, reaction_id, ok="Afgewezen.", go_to="/mijn"
    )


@router.post("/listings/{listing_id}/remove")
def remove(
    request: Request,
    background: BackgroundTasks,
    listing_id: int,
    user=Depends(require_user),
    db=Depends(get_db),
):
    return run_action(
        request,
        db,
        background,
        listings.remove_listing,
        user,
        listing_id,
        ok="Dienst weggehaald.",
        go_to="/mijn",
    )


@router.post("/listings/{listing_id}/mail-sent")
def mail_sent(
    request: Request,
    background: BackgroundTasks,
    listing_id: int,
    user=Depends(require_user),
    db=Depends(get_db),
):
    return run_action(
        request,
        db,
        background,
        listings.mark_mail_sent,
        user,
        listing_id,
        ok="Genoteerd.",
        go_to=f"/mijn#l{listing_id}",
    )
