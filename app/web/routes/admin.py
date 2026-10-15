"""Beheer: invite links, members, the zaal/werkplek lists, the planning mail template, and
removing someone's listing. Every route here requires an admin."""

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User
from app.services import appdata, demo, invites, listings, logins, members, planning
from app.services.errors import UserError
from app.services.transaction import run_write
from app.web.responses import flash, redirect, render, run_action, safe_next, send_queued
from app.web.session import require_admin

router = APIRouter(prefix="/beheer")
ADMIN_LOGIN_LINK_MINUTES = 24 * 60


def _page(request: Request, db: Session, user: User, **ctx):
    """The whole Beheer page. Freshly made links are passed in `ctx` to show them once."""
    settings = get_settings()
    main = invites.main_link(db)
    subject, body = planning.template(db)
    trade_subject, trade_body = planning.template(db, trade=True)
    return render(
        request,
        "admin.html",
        db=db,
        user=user,
        main=main,
        main_url=invites.url(settings, main),
        links=[(link, invites.url(settings, link)) for link in invites.extra_links(db)],
        users=members.all_members(db),
        halls=appdata.get_list(db, "halls"),
        workplaces=appdata.get_list(db, "workplaces"),
        mail_subject=subject,
        mail_body=body,
        trade_subject=trade_subject,
        trade_body=trade_body,
        placeholders=planning.PLACEHOLDERS,
        demo_count=len(demo.demo_user_ids(db)),
        **ctx,
    )


@router.get("", response_class=HTMLResponse)
def admin_page(request: Request, user=Depends(require_admin), db=Depends(get_db)):
    return _page(request, db, user)


# ---------------------------------------------------------------- invite links


def _optional_int(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    if not value.isdigit():
        raise UserError("Vul een heel getal in, of laat het leeg.")
    return int(value)


@router.post("/links", response_class=HTMLResponse)
def create_link(
    request: Request,
    label: str = Form(""),
    role: str = Form("member"),
    max_uses: str = Form(""),
    valid_days: str = Form(""),
    user=Depends(require_admin),
    db=Depends(get_db),
):
    try:
        link = invites.create_link(
            db,
            user,
            label=label,
            role=role,
            max_uses=_optional_int(max_uses),
            valid_days=_optional_int(valid_days),
        )
    except UserError as e:
        flash(request, str(e), "error")
        return redirect("/beheer#links")
    return _page(request, db, user, new_link=(link, invites.url(get_settings(), link)))


@router.post("/links/main")
def renew_main_link(request: Request, user=Depends(require_admin), db=Depends(get_db)):
    invites.renew_main_link(db, user)
    flash(request, "Nieuwe groepslink gemaakt. De oude werkt niet meer: zet de nieuwe in de groep.")
    return redirect("/beheer#links")


@router.post("/links/{link_id}/revoke")
def revoke_link(request: Request, link_id: int, user=Depends(require_admin), db=Depends(get_db)):
    try:
        invites.revoke_link(db, link_id)
    except UserError as e:
        flash(request, str(e), "error")
    else:
        flash(request, "Link ingetrokken.")
    return redirect("/beheer#links")


# ---------------------------------------------------------------- members


@router.post("/users/{user_id}/link", response_class=HTMLResponse)
def login_link(request: Request, user_id: int, user=Depends(require_admin), db=Depends(get_db)):
    """A one-time login link for a member who lost their phone (valid 24 hours)."""
    target = db.get(User, user_id)
    if target is None:
        flash(request, "Dat lid bestaat niet (meer).", "error")
        return redirect("/beheer#leden")
    link = logins.make_link(db, get_settings(), target, minutes=ADMIN_LOGIN_LINK_MINUTES)
    return _page(request, db, user, user_link=(target, link))


@router.post("/users/{user_id}/admin")
def toggle_admin(request: Request, user_id: int, user=Depends(require_admin), db=Depends(get_db)):
    target = db.get(User, user_id)
    if target is None:
        flash(request, "Dat lid bestaat niet (meer).", "error")
        return redirect("/beheer#leden")
    try:
        members.set_admin(db, target, not target.is_admin)
        db.commit()
    except UserError as e:
        flash(request, str(e), "error")
    else:
        flash(request, f"{target.name} is {'nu' if target.is_admin else 'geen'} beheerder.")
    # An admin who just demoted themselves can't see Beheer anymore.
    return redirect("/beheer#leden" if user.is_admin else "/aangeboden")


@router.post("/users/{user_id}/delete")
def delete_member(
    request: Request,
    background: BackgroundTasks,
    user_id: int,
    user=Depends(require_admin),
    db=Depends(get_db),
):
    target = db.get(User, user_id)
    if target is None or target.id == user.id:
        flash(request, "Je eigen account verwijder je via Account.", "error")
        return redirect("/beheer#leden")
    name = target.name
    try:
        run_write(db, lambda db: members.delete_user(db, db.get(User, user_id)))
    except UserError as e:
        flash(request, str(e), "error")
    else:
        send_queued(db, background)
        flash(request, f"{name} en alle gegevens zijn verwijderd.")
    return redirect("/beheer#leden")


# ---------------------------------------------------------------- listings


@router.post("/listings/{listing_id}/delete")
def delete_listing(
    request: Request,
    background: BackgroundTasks,
    listing_id: int,
    next: str = Form(""),
    user=Depends(require_admin),
    db=Depends(get_db),
):
    return run_action(
        request,
        db,
        background,
        listings.admin_remove_listing,
        user,
        listing_id,
        ok="Dienst verwijderd.",
        go_to=safe_next(next, "/aangeboden"),
    )


# ---------------------------------------------------------------- lists and mail template


@router.post("/lijsten")
def save_lists(
    request: Request,
    halls: str = Form(""),
    workplaces: str = Form(""),
    user=Depends(require_admin),
    db=Depends(get_db),
):
    appdata.set_list(db, "halls", halls.splitlines())
    appdata.set_list(db, "workplaces", workplaces.splitlines())
    flash(request, "Lijsten opgeslagen.")
    return redirect("/beheer#lijsten")


@router.post("/mail")
def save_mail_template(
    request: Request,
    subject: str = Form(""),
    body: str = Form(""),
    trade_subject: str = Form(""),
    trade_body: str = Form(""),
    reset: str = Form(""),
    user=Depends(require_admin),
    db=Depends(get_db),
):
    if reset:
        planning.reset_templates(db)
        flash(request, "Standaardmail teruggezet.")
    else:
        planning.save_template(db, subject, body)
        planning.save_template(db, trade_subject, trade_body, trade=True)
        flash(request, "Mail opgeslagen.")
    return redirect("/beheer#mail")


# ---------------------------------------------------------------- demo data


@router.post("/demo/remove")
def remove_demo(
    request: Request,
    background: BackgroundTasks,
    user=Depends(require_admin),
    db=Depends(get_db),
):
    removed = run_write(db, demo.remove)
    send_queued(db, background)
    flash(request, f"{removed} demo-collega's en hun diensten verwijderd.")
    return redirect("/beheer")
