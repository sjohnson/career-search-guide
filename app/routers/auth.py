"""Authentication routes: login, register, logout."""

from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.config import ALLOW_REGISTRATION
from app.database import get_db
from app.services.auth import (
    authenticate_user,
    create_user,
    registration_allowed,
)
from app.services.csrf import ensure_csrf_token, validate_csrf_token
from app.templating import templates

router = APIRouter(tags=["auth"])


def _safe_next_path(next_path: str | None) -> str:
    if not next_path:
        return "/"
    parsed = urlparse(next_path)
    if parsed.scheme or parsed.netloc:
        return "/"
    if not next_path.startswith("/"):
        return "/"
    return next_path


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, db: Session = Depends(get_db), next: str = ""):
    ensure_csrf_token(request)
    return templates.TemplateResponse(
        request,
        "auth/login.html",
        {
            "next": next,
            "show_register_link": registration_allowed(db, allow_registration=ALLOW_REGISTRATION),
        },
    )


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    db: Session = Depends(get_db),
):
    form = await request.form()
    validate_csrf_token(request, str(form.get("csrf_token", "")))
    email = str(form.get("email", ""))
    password = str(form.get("password", ""))
    next_path = str(form.get("next", ""))
    user = authenticate_user(db, email, password)
    if not user:
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {
                "error": "Invalid email or password.",
                "email": email,
                "next": next_path,
                "show_register_link": registration_allowed(db, allow_registration=ALLOW_REGISTRATION),
            },
            status_code=401,
        )

    request.session["user_id"] = user.id
    ensure_csrf_token(request)
    return RedirectResponse(url=_safe_next_path(next_path), status_code=303)


@router.get("/register", response_class=HTMLResponse)
def register_form(request: Request, db: Session = Depends(get_db)):
    if not registration_allowed(db, allow_registration=ALLOW_REGISTRATION):
        return RedirectResponse(url="/login", status_code=303)

    ensure_csrf_token(request)
    return templates.TemplateResponse(request, "auth/register.html", {})


@router.post("/register", response_class=HTMLResponse)
async def register_submit(
    request: Request,
    db: Session = Depends(get_db),
):
    if not registration_allowed(db, allow_registration=ALLOW_REGISTRATION):
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()
    validate_csrf_token(request, str(form.get("csrf_token", "")))
    email = str(form.get("email", ""))
    password = str(form.get("password", ""))
    password_confirm = str(form.get("password_confirm", ""))
    if password != password_confirm:
        return templates.TemplateResponse(
            request,
            "auth/register.html",
            {"error": "Passwords do not match.", "email": email},
            status_code=400,
        )

    try:
        user = create_user(db, email, password)
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "auth/register.html",
            {"error": str(exc), "email": email},
            status_code=400,
        )

    request.session["user_id"] = user.id
    ensure_csrf_token(request)
    return RedirectResponse(url="/", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
