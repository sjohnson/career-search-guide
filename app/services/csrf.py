"""CSRF token helpers for session-backed forms and HTMX requests."""

import secrets

from fastapi import HTTPException, Request

CSRF_SESSION_KEY = "csrf_token"
CSRF_FORM_FIELD = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"


def ensure_csrf_token(request: Request) -> str:
    token = request.session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[CSRF_SESSION_KEY] = token
    return token


def validate_csrf_token(request: Request, token: str | None = None) -> None:
    session_token = request.session.get(CSRF_SESSION_KEY)
    if not session_token:
        raise HTTPException(status_code=403, detail="CSRF token missing from session.")

    submitted = token or request.headers.get(CSRF_HEADER)
    if not submitted or not secrets.compare_digest(submitted, session_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token.")
