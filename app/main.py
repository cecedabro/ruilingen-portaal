"""The FastAPI application: middleware, error pages, routes and the cleanup loop.

Request flow: SessionMiddleware (signed cookie) → `guard` (CSRF check, security headers) →
a route in app/web/routes → services in app/services → SQLite. See docs/architecture.md.
"""

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.db import SessionLocal
from app.services.housekeeping import cleanup
from app.web.responses import APP_DIR, redirect, render
from app.web.routes import ROUTERS
from app.web.session import Forbidden, LoginRequired, same_origin

logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s %(message)s")
log = logging.getLogger("ruilingen")
settings = get_settings()

CLEANUP_EVERY_SECONDS = 6 * 3600
CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "form-action 'self' mailto:; frame-ancestors 'none'; base-uri 'none'"
)


async def _housekeeping_loop() -> None:
    """Delete old data a few times a day (runs inside the single app process)."""
    while True:
        try:
            with SessionLocal() as db:
                cleanup(db, settings, settings.today())
        except Exception:
            log.exception("cleanup failed")
        await asyncio.sleep(CLEANUP_EVERY_SECONDS)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(_housekeeping_loop())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
for router in ROUTERS:
    app.include_router(router)


@app.middleware("http")
async def guard(request: Request, call_next):
    """Refuse cross-site POSTs, and add security and caching headers to every response."""
    if request.method not in ("GET", "HEAD", "OPTIONS") and not same_origin(request):
        return PlainTextResponse("Verzoek van een andere site geweigerd.", status_code=403)
    response = await call_next(request)
    headers = response.headers
    headers.setdefault("Content-Security-Policy", CSP)
    headers.setdefault("X-Content-Type-Options", "nosniff")
    headers.setdefault("Referrer-Policy", "same-origin")
    headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.url.path.startswith("/static/"):
        # Asset URLs carry ?v=<hash of the files>, so they can be cached forever.
        headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
    else:
        headers.setdefault("Cache-Control", "no-store")
    return response


# Middleware added later wraps earlier ones: the session must be there before `guard` runs.
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
    target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    return redirect(f"/login?next={target}" if request.method == "GET" else "/login")


@app.exception_handler(Forbidden)
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
