"""Your own account: name, optional notification email, devices, deleting it."""

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse

from app.config import get_settings
from app.db import get_db
from app.models import User
from app.services import logins, members
from app.services.errors import UserError
from app.services.transaction import run_write
from app.web.responses import flash, redirect, render, send_queued
from app.web.session import log_out, require_user

router = APIRouter()


def _account_page(request: Request, db, user, **ctx):
    return render(
        request,
        "account.html",
        db=db,
        user=user,
        pending_email=logins.pending_email(db, user),
        **ctx,
    )


@router.get("/account", response_class=HTMLResponse)
def account(request: Request, user=Depends(require_user), db=Depends(get_db)):
    return _account_page(request, db, user)


@router.post("/account")
def save(
    request: Request,
    name: str = Form(""),
    email_notifications: bool = Form(False),
    user=Depends(require_user),
    db=Depends(get_db),
):
    try:
        user.name = members.check_name(db, name, exclude_id=user.id)
    except UserError as e:
        flash(request, str(e), "error")
        return redirect("/account")
    if user.email:  # the checkbox is only shown when there is an address
        user.email_notifications = email_notifications
    db.commit()
    flash(request, "Opgeslagen.")
    return redirect("/account")


@router.post("/account/email")
def set_email(
    request: Request,
    background: BackgroundTasks,
    email: str = Form(""),
    user=Depends(require_user),
    db=Depends(get_db),
):
    """Add or change the address: a confirmation mail is sent first, and the address is only
    saved once its link is opened (so a typo never replaces a working address)."""
    settings = get_settings()
    if not settings.mail_enabled:
        return redirect("/account")
    try:
        link = logins.request_email_change(db, settings, user, email)
    except UserError as e:
        flash(request, str(e), "error")
        return redirect("/account#email")
    send_queued(db, background)
    flash(request, "Bevestiging verstuurd. Klik op de link in de mail om het adres te bevestigen.")
    if settings.dev_mode:
        flash(request, f"Ontwikkelmodus: {link}")
    return redirect("/account#email")


@router.post("/account/email/remove")
def remove_email(request: Request, user=Depends(require_user), db=Depends(get_db)):
    """Delete the address from the database (and any unconfirmed attempt)."""
    logins.remove_email(db, user)
    flash(request, "Je e-mailadres is verwijderd.")
    return redirect("/account#email")


@router.post("/account/device-link", response_class=HTMLResponse)
def device_link(request: Request, user=Depends(require_user), db=Depends(get_db)):
    """A one-time link to open on another device (shown once, on this page)."""
    link = logins.make_link(db, get_settings(), user)
    return _account_page(request, db, user, device_link=link)


@router.post("/account/logout-everywhere")
def logout_everywhere(request: Request, user=Depends(require_user), db=Depends(get_db)):
    user.session_epoch += 1  # every existing session cookie is now stale
    db.commit()
    log_out(request)
    flash(request, "Je bent overal uitgelogd.")
    return redirect("/login")


@router.post("/account/delete")
def delete_account(
    request: Request,
    background: BackgroundTasks,
    confirm: str = Form(""),
    user=Depends(require_user),
    db=Depends(get_db),
):
    if confirm.strip().lower() != "verwijder":
        flash(request, 'Typ "verwijder" om je account te verwijderen.', "error")
        return redirect("/account")
    try:
        run_write(db, lambda db: members.delete_user(db, db.get(User, user.id)))
    except UserError as e:
        flash(request, str(e), "error")
        return redirect("/account")
    send_queued(db, background)
    log_out(request)
    flash(request, "Je account en al je gegevens zijn verwijderd.")
    return redirect("/login")
