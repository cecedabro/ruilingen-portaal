"""Getting in: invite links (/join), one-time login links (/login/<token>), and confirming a
notification address (/email/<token>). There is no password and no email login."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from app.db import get_db
from app.services import invites, logins
from app.services.errors import UserError
from app.web.responses import flash, redirect, render, safe_next
from app.web.session import current_user, log_in, log_out

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str | None = None, user=Depends(current_user)):
    if user:
        return redirect(safe_next(next, "/aangeboden"))
    return render(request, "login.html")


@router.post("/logout")
def logout(request: Request):
    log_out(request)
    return redirect("/login")


# ---------------------------------------------------------------- invite links


def _join_page(request, db, code: str, name: str = "", error: str = "", status_code=200):
    link = invites.usable_link(db, code)
    return render(request, "join.html", link=link, name=name, error=error, status_code=status_code)


@router.get("/join/{code}", response_class=HTMLResponse)
def join_form(request: Request, code: str, user=Depends(current_user), db=Depends(get_db)):
    if user:
        return redirect("/aangeboden")
    return _join_page(request, db, code)


@router.post("/join/{code}", response_class=HTMLResponse)
def join_submit(request: Request, code: str, name: str = Form(""), db=Depends(get_db)):
    try:
        user = invites.join(db, code, name)
    except UserError as e:
        db.rollback()
        return _join_page(request, db, code, name, str(e), status_code=422)
    log_in(request, user)
    if user.is_admin:
        flash(request, "Welkom! Je bent beheerder: zie Beheer onderaan de pagina.")
    return redirect("/aangeboden")


# ---------------------------------------------------------------- one-time links


@router.get("/login/{token}", response_class=HTMLResponse)
def login_link(request: Request, token: str, next: str | None = None, db=Depends(get_db)):
    """Only shows a button: link previews (chat apps, mail scanners) must not burn the link."""
    found = logins.find_token(db, token)
    if found is not None and found.email:  # an address-verification link, see /email/
        found = None
    return render(
        request,
        "login_confirm.html",
        valid=found is not None,
        name=found.user.first_name if found else "",
        next=safe_next(next, ""),
    )


@router.post("/login/{token}")
def login_link_use(request: Request, token: str, next: str = Form(""), db=Depends(get_db)):
    user = logins.consume_login(db, token)
    if user is None:
        flash(request, "Deze link is verlopen of al gebruikt. Vraag een nieuwe aan.", "error")
        return redirect("/login")
    log_in(request, user)
    return redirect(safe_next(next, "/aangeboden"))


@router.get("/email/{token}", response_class=HTMLResponse)
def email_link(request: Request, token: str, db=Depends(get_db)):
    found = logins.find_token(db, token)
    valid = found is not None and bool(found.email)
    return render(request, "email_confirm.html", valid=valid, email=found.email if valid else "")


@router.post("/email/{token}", response_class=HTMLResponse)
def email_link_use(request: Request, token: str, db=Depends(get_db)):
    """Confirms the address only; it does not log in on this device."""
    user = logins.verify_email(db, token)
    return render(request, "email_confirm.html", done=user is not None, valid=False, email="")
