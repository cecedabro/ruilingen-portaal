from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User
from app.web.responses import redirect, render, safe_next
from app.web.session import current_user

router = APIRouter()


@router.api_route("/healthz", methods=["GET", "HEAD"], include_in_schema=False)
def healthz(db: Session = Depends(get_db)):
    """Used by the Kubernetes probes and the homelab status page: must stay public."""
    db.execute(select(1))
    return PlainTextResponse("ok")


@router.get("/")
def home(user: User | None = Depends(current_user)):
    return redirect("/aangeboden" if user else "/login")


@router.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request, user: User | None = Depends(current_user), db=Depends(get_db)):
    return render(request, "privacy.html", db=db, user=user)


@router.post("/theme")
def toggle_theme(request: Request, next: str = Form("")):
    """Light/dark switch, remembered per device in a cookie. app.js flips it instantly
    without this round-trip; this is the fallback without JavaScript."""
    theme = "light" if request.cookies.get("theme") == "dark" else "dark"
    response = redirect(safe_next(next, "/"))
    response.set_cookie(
        "theme", theme, max_age=365 * 86400, samesite="lax", secure=get_settings().secure_cookies
    )
    return response
