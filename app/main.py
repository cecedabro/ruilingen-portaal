import asyncio
import contextlib
import logging
import secrets
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app import auth, services
from app.auth import LoginRequired, current_user, require_admin, require_user
from app.config import get_settings
from app.db import SessionLocal, get_db
from app.models import Kind, Listing, Notification, User, utcnow
from app.services import Deal, SwapError
from app.shifts import planning_mail
from app.web import flash, redirect, render, safe_next, send_queued

logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s %(message)s")
log = logging.getLogger("ruilingen")
settings = get_settings()


def bootstrap_admins(db: Session) -> None:
    for email in settings.admin_email_list:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            db.add(User(email=email, name=email.split("@")[0].title(), is_admin=True))
        elif not user.is_admin:
            user.is_admin = True
    db.commit()


async def housekeeping_loop() -> None:
    while True:
        try:
            with SessionLocal() as db:
                services.cleanup(db, settings, services.local_today(settings))
        except Exception:
            log.exception("cleanup failed")
        await asyncio.sleep(6 * 3600)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    with SessionLocal() as db:
        bootstrap_admins(db)
    task = asyncio.create_task(housekeeping_loop())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "form-action 'self' mailto:; frame-ancestors 'none'; base-uri 'none'"
)


@app.middleware("http")
async def guard(request: Request, call_next):
    if request.method not in {"GET", "HEAD", "OPTIONS"} and not auth.same_origin(request):
        return PlainTextResponse("Verzoek van een andere site geweigerd.", status_code=403)
    response = await call_next(request)
    response.headers.setdefault("Content-Security-Policy", CSP)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.url.path.startswith("/static/"):
        # URLs carry ?v=<hash of the files>, so they can be cached forever.
        response.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
    else:
        response.headers.setdefault("Cache-Control", "no-store")
    return response


# Added after @middleware so it runs first and the session is available inside `guard`.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    session_cookie="ruilingen_session",
    max_age=settings.session_days * 86400,
    same_site="lax",
    https_only=settings.secure_cookies,
)
app.add_middleware(GZipMiddleware, minimum_size=600)


@app.exception_handler(LoginRequired)
async def _login_required(request: Request, _exc):
    target = request.url.path
    if request.url.query:
        target += "?" + request.url.query
    return redirect(f"/login?next={target}" if request.method == "GET" else "/login")


@app.exception_handler(auth.Forbidden)
async def _forbidden(request: Request, _exc):
    return PlainTextResponse("Alleen voor beheerders.", status_code=403)


@app.exception_handler(404)
async def _not_found(request: Request, _exc):
    return render(
        request,
        "error.html",
        status_code=404,
        title="Niet gevonden",
        text="Deze pagina bestaat niet (meer).",
    )


def today() -> date:
    return services.local_today(settings)


def act(
    request: Request,
    db: Session,
    background: BackgroundTasks,
    fn: Callable,
    *args,
    ok: str | None,
    next_url: str | None,
    default: str,
    anchor: str = "",
    **kwargs,
) -> Response:
    """Run one state change, flash the result and redirect (POST → redirect → GET)."""
    try:
        services.run_write(db, fn, *args, **kwargs)
    except SwapError as e:
        flash(request, str(e), "error")
    else:
        send_queued(db, background)
        if ok:
            flash(request, ok)
    return redirect(safe_next(next_url, default) + anchor)


# ---------------------------------------------------------------- misc


@app.api_route("/healthz", methods=["GET", "HEAD"], include_in_schema=False)
def healthz(db: Session = Depends(get_db)):
    db.execute(select(1))
    return PlainTextResponse("ok")


@app.get("/")
def home(user: User | None = Depends(current_user)):
    return redirect("/aangeboden" if user else "/login")


@app.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request, user: User | None = Depends(current_user), db=Depends(get_db)):
    return render(request, "privacy.html", db=db, user=user)


# ---------------------------------------------------------------- login


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str | None = None, user=Depends(current_user)):
    if user:
        return redirect(safe_next(next, "/aangeboden"))
    return render(request, "login.html", next=safe_next(next, ""))


@app.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    background: BackgroundTasks,
    email: str = Form(""),
    next: str = Form(""),
    db: Session = Depends(get_db),
):
    db.info["mails"] = []
    link = auth.request_login(db, settings, email, next_path=safe_next(next, ""))
    db.commit()
    send_queued(db, background)
    return render(
        request,
        "login_sent.html",
        email=auth.normalise_email(email),
        dev_link=link if settings.dev_mode else None,
    )


@app.get("/join/{code}", response_class=HTMLResponse)
def join_form(request: Request, code: str, user=Depends(current_user), db=Depends(get_db)):
    if user:
        return redirect("/aangeboden")
    valid = secrets.compare_digest(code, auth.join_code(db))
    return render(request, "join.html", code=code, valid=valid, name="")


@app.post("/join/{code}", response_class=HTMLResponse)
def join_submit(request: Request, code: str, name: str = Form(""), db=Depends(get_db)):
    try:
        user = auth.join(db, code, name)
    except SwapError as e:
        db.rollback()
        return render(
            request, "join.html", code=code, valid=True, name=name, error=str(e), status_code=422
        )
    auth.log_in(request, user)
    return redirect("/aangeboden")


@app.get("/login/{token}", response_class=HTMLResponse)
def login_confirm(request: Request, token: str, next: str | None = None, db=Depends(get_db)):
    found = auth.find_token(db, token)
    return render(
        request,
        "login_confirm.html",
        valid=found is not None,
        name=found.user.first_name if found else "",
        next=safe_next(next, ""),
    )


@app.post("/login/{token}")
def login_finish(request: Request, token: str, next: str = Form(""), db=Depends(get_db)):
    user = auth.consume_token(db, token)
    if user is None:
        flash(request, "Deze link is verlopen of al gebruikt. Vraag een nieuwe aan.", "error")
        return redirect("/login")
    auth.log_in(request, user)
    return redirect(safe_next(next, "/aangeboden"))


@app.post("/logout")
def logout(request: Request):
    auth.log_out(request)
    return redirect("/login")


# ---------------------------------------------------------------- boards


def _board(request: Request, db: Session, user: User, kind: Kind, soort: str):
    items = services.open_listings(db, kind, today())
    ranked = list(enumerate(items, start=1))  # rank = order of posting, before filtering
    if soort in {"H", "G", "C", "P", "R", "I"}:
        ranked = [
            (rank, item)
            for rank, item in ranked
            if soort in (item.shift_type or "") + "".join(item.wanted_type_list)
        ]
    else:
        soort = ""
    return render(
        request,
        "board.html",
        db=db,
        user=user,
        kind=kind,
        ranked=ranked,
        soort=soort,
        tab=kind.value,
        today=today(),
    )


@app.get("/aangeboden", response_class=HTMLResponse)
def offers(request: Request, soort: str = "", user=Depends(require_user), db=Depends(get_db)):
    return _board(request, db, user, Kind.OFFER, soort)


@app.get("/gezocht", response_class=HTMLResponse)
def wanted(request: Request, soort: str = "", user=Depends(require_user), db=Depends(get_db)):
    return _board(request, db, user, Kind.WANTED, soort)


@app.get("/mijn", response_class=HTMLResponse)
def mine(request: Request, user=Depends(require_user), db=Depends(get_db)):
    items = []
    for listing in services.my_listings(db, user, today()):
        deal = Deal.of(listing)
        mail = None
        if deal:
            mail = planning_mail(
                planning=settings.planning_email,
                giver_name=deal.giver.name,
                giver_email=deal.giver.email,
                taker_name=deal.taker.name,
                taker_email=deal.taker.email,
                day=deal.day,
                start=deal.start,
                end=deal.end,
                code=deal.code,
            )
        items.append((listing, deal, mail))
    return render(request, "mine.html", db=db, user=user, items=items, tab="mijn")


# ---------------------------------------------------------------- posting


@app.get("/plaatsen", response_class=HTMLResponse)
def post_form(
    request: Request, soort: str = "aanbod", user=Depends(require_user), db=Depends(get_db)
):
    kind = Kind.WANTED if soort == "gezocht" else Kind.OFFER
    return render(
        request, "post.html", db=db, user=user, kind=kind, tab="plaatsen", today=today(), form={}
    )


@app.post("/plaatsen", response_class=HTMLResponse)
def post_submit(
    request: Request,
    kind: Kind = Form(...),
    day: str = Form(""),
    start: str = Form(""),
    end: str = Form(""),
    code: str = Form(""),
    codes: list[str] = Form([]),
    note: str = Form(""),
    user=Depends(require_user),
    db=Depends(get_db),
):
    try:
        parsed_day = date.fromisoformat(day)
    except ValueError:
        parsed_day = None
    try:
        if parsed_day is None:
            raise SwapError("Kies een datum.")
        if kind == Kind.OFFER:
            listing = services.run_write(
                db,
                services.create_offer,
                user,
                day=parsed_day,
                start=start,
                end=end,
                code=code,
                note=note,
                today=today(),
            )
        else:
            listing = services.run_write(
                db,
                services.create_wanted,
                user,
                day=parsed_day,
                codes=codes,
                note=note,
                today=today(),
            )
    except SwapError as e:
        form = dict(day=day, start=start, end=end, code=code, codes=codes, note=note)
        return render(
            request,
            "post.html",
            db=db,
            user=user,
            kind=kind,
            tab="plaatsen",
            today=today(),
            form=form,
            error=str(e),
            status_code=422,
        )
    flash(request, "Geplaatst.")
    return redirect(("/aangeboden" if kind == Kind.OFFER else "/gezocht") + f"#l{listing.id}")


# ---------------------------------------------------------------- reactions


@app.post("/listings/{listing_id}/react")
def react(
    request: Request,
    background: BackgroundTasks,
    listing_id: int,
    next: str = Form(""),
    offer_start: str | None = Form(None),
    offer_end: str | None = Form(None),
    offer_type: str | None = Form(None),
    user=Depends(require_user),
    db=Depends(get_db),
):
    return act(
        request,
        db,
        background,
        services.react,
        user,
        listing_id,
        today=today(),
        offer_start=offer_start,
        offer_end=offer_end,
        offer_type=offer_type,
        ok="Gereageerd.",
        next_url=next,
        default="/aangeboden",
        anchor=f"#l{listing_id}",
    )


@app.post("/reactions/{reaction_id}/withdraw")
def withdraw(
    request: Request,
    background: BackgroundTasks,
    reaction_id: int,
    next: str = Form(""),
    user=Depends(require_user),
    db=Depends(get_db),
):
    return act(
        request,
        db,
        background,
        services.withdraw,
        user,
        reaction_id,
        ok="Ingetrokken.",
        next_url=next,
        default="/mijn",
    )


@app.post("/reactions/{reaction_id}/decline")
def decline(
    request: Request,
    background: BackgroundTasks,
    reaction_id: int,
    user=Depends(require_user),
    db=Depends(get_db),
):
    return act(
        request,
        db,
        background,
        services.decline,
        user,
        reaction_id,
        ok="Afgewezen.",
        next_url=None,
        default="/mijn",
    )


@app.post("/reactions/{reaction_id}/accept")
def accept(
    request: Request,
    background: BackgroundTasks,
    reaction_id: int,
    user=Depends(require_user),
    db=Depends(get_db),
):
    return act(
        request,
        db,
        background,
        services.accept,
        user,
        reaction_id,
        today=today(),
        ok="Rond! Stuur nu de mail naar planning.",
        next_url=None,
        default="/mijn",
    )


@app.post("/listings/{listing_id}/remove")
def remove(
    request: Request,
    background: BackgroundTasks,
    listing_id: int,
    user=Depends(require_user),
    db=Depends(get_db),
):
    return act(
        request,
        db,
        background,
        services.remove_listing,
        user,
        listing_id,
        ok="Dienst weggehaald.",
        next_url=None,
        default="/mijn",
    )


@app.post("/listings/{listing_id}/mail-sent")
def mail_sent(
    request: Request,
    background: BackgroundTasks,
    listing_id: int,
    user=Depends(require_user),
    db=Depends(get_db),
):
    return act(
        request,
        db,
        background,
        services.mark_mail_sent,
        user,
        listing_id,
        ok="Genoteerd.",
        next_url=None,
        default="/mijn",
    )


# ---------------------------------------------------------------- notifications


@app.get("/meldingen", response_class=HTMLResponse)
def notifications(request: Request, user=Depends(require_user), db=Depends(get_db)):
    items = list(
        db.scalars(
            select(Notification)
            .where(Notification.user_id == user.id)
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(100)
        )
    )
    unread_ids = {n.id for n in items if n.read_at is None}
    response = render(
        request,
        "notifications.html",
        db=db,
        user=user,
        items=items,
        unread_ids=unread_ids,
        unread=0,
    )
    if unread_ids:
        db.execute(
            update(Notification)
            .where(Notification.user_id == user.id, Notification.read_at.is_(None))
            .values(read_at=utcnow())
        )
        db.commit()
    return response


# ---------------------------------------------------------------- account


@app.get("/account", response_class=HTMLResponse)
def account(request: Request, user=Depends(require_user), db=Depends(get_db)):
    return render(request, "account.html", db=db, user=user)


@app.post("/account")
def account_save(
    request: Request,
    name: str = Form(""),
    email_notifications: bool = Form(False),
    user=Depends(require_user),
    db=Depends(get_db),
):
    try:
        user.name = auth.check_name(db, name, exclude_id=user.id)
    except SwapError as e:
        flash(request, str(e), "error")
        return redirect("/account")
    if user.email:  # the checkbox is only shown when there is an address
        user.email_notifications = email_notifications
    db.commit()
    flash(request, "Opgeslagen.")
    return redirect("/account")


@app.post("/account/email")
def account_email(
    request: Request,
    background: BackgroundTasks,
    email: str = Form(""),
    user=Depends(require_user),
    db=Depends(get_db),
):
    if not settings.mail_enabled:
        return redirect("/account")
    if not email.strip():
        user.email = None
        db.commit()
        flash(request, "E-mailadres verwijderd.")
        return redirect("/account")
    db.info["mails"] = []
    try:
        link = auth.request_email_change(db, settings, user, email)
    except SwapError as e:
        flash(request, str(e), "error")
        return redirect("/account")
    send_queued(db, background)
    flash(request, "Check je mail en klik op de link om het adres te bevestigen.")
    if settings.dev_mode:
        flash(request, f"Ontwikkelmodus: {link}")
    return redirect("/account")


@app.post("/account/device-link", response_class=HTMLResponse)
def device_link(request: Request, user=Depends(require_user), db=Depends(get_db)):
    link = auth.make_link(db, settings, user)
    return render(request, "account.html", db=db, user=user, device_link=link)


@app.post("/account/logout-everywhere")
def logout_everywhere(request: Request, user=Depends(require_user), db=Depends(get_db)):
    user.session_epoch += 1
    db.commit()
    auth.log_out(request)
    flash(request, "Je bent overal uitgelogd.")
    return redirect("/login")


@app.post("/account/delete")
def account_delete(
    request: Request,
    background: BackgroundTasks,
    confirm: str = Form(""),
    user=Depends(require_user),
    db=Depends(get_db),
):
    if confirm.strip().lower() != "verwijder":
        flash(request, 'Typ "verwijder" om je account te verwijderen.', "error")
        return redirect("/account")

    def _delete(db: Session, user: User) -> None:
        # Close open listings properly first, so people who reacted get told.
        for listing in db.scalars(select(Listing).where(Listing.user_id == user.id)):
            if listing.status == "open":
                services.remove_listing(db, user, listing.id)
        db.flush()
        db.delete(user)

    services.run_write(db, _delete, user)
    send_queued(db, background)
    auth.log_out(request)
    flash(request, "Je account en al je gegevens zijn verwijderd.")
    return redirect("/login")


# ---------------------------------------------------------------- admin


def _admin_page(request: Request, db: Session, user: User, **ctx):
    users = list(db.scalars(select(User).order_by(User.is_active.desc(), func.lower(User.name))))
    return render(
        request,
        "admin.html",
        db=db,
        user=user,
        users=users,
        join_url=auth.join_link(db, settings),
        **ctx,
    )


@app.get("/beheer", response_class=HTMLResponse)
def admin(request: Request, user=Depends(require_admin), db=Depends(get_db)):
    return _admin_page(request, db, user)


@app.post("/beheer/join-link")
def admin_rotate(request: Request, user=Depends(require_admin), db=Depends(get_db)):
    auth.rotate_join_code(db)
    flash(request, "Nieuwe link gemaakt. De oude werkt niet meer; deel de nieuwe in de groep.")
    return redirect("/beheer")


@app.post("/beheer/users/{user_id}/link", response_class=HTMLResponse)
def admin_user_link(
    request: Request, user_id: int, user=Depends(require_admin), db=Depends(get_db)
):
    target = db.get(User, user_id)
    if target is None or not target.is_active:
        flash(request, "Dat kan niet.", "error")
        return redirect("/beheer")
    link = auth.make_link(db, settings, target, minutes=60 * 24)
    return _admin_page(request, db, user, user_link=(target, link))


@app.post("/beheer/users/{user_id}/toggle")
def admin_toggle(request: Request, user_id: int, user=Depends(require_admin), db=Depends(get_db)):
    target = db.get(User, user_id)
    if target is None or target.id == user.id:
        flash(request, "Dat kan niet.", "error")
        return redirect("/beheer")
    target.is_active = not target.is_active
    db.commit()
    flash(request, f"{target.name} is {'weer actief' if target.is_active else 'geblokkeerd'}.")
    return redirect("/beheer")


@app.post("/beheer/users/{user_id}/admin")
def admin_role(request: Request, user_id: int, user=Depends(require_admin), db=Depends(get_db)):
    target = db.get(User, user_id)
    if target is None or target.id == user.id:
        flash(request, "Dat kan niet.", "error")
        return redirect("/beheer")
    target.is_admin = not target.is_admin
    db.commit()
    flash(request, f"{target.name} is {'nu' if target.is_admin else 'geen'} beheerder.")
    return redirect("/beheer")
