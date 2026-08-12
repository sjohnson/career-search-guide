"""CSRF validation for mutating HTTP methods."""

import secrets

from starlette.requests import Request
from starlette.responses import Response

from app.services.csrf import CSRF_FORM_FIELD, CSRF_HEADER, CSRF_SESSION_KEY

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_EXEMPT_PATHS = frozenset({"/login", "/register"})


async def csrf_middleware(request: Request, call_next):
    if (
        request.method in SAFE_METHODS
        or request.url.path.startswith("/static")
        or request.url.path in CSRF_EXEMPT_PATHS
    ):
        return await call_next(request)

    session_token = request.session.get(CSRF_SESSION_KEY)
    if not session_token:
        return Response("CSRF token missing from session.", status_code=403)

    header = request.headers.get(CSRF_HEADER)
    if header and secrets.compare_digest(header, session_token):
        return await call_next(request)

    content_type = request.headers.get("content-type", "")
    if content_type.startswith("application/x-www-form-urlencoded") or "multipart/form-data" in content_type:
        form = await request.form()
        form_token = form.get(CSRF_FORM_FIELD)
        if form_token and secrets.compare_digest(str(form_token), session_token):
            return await call_next(request)

    return Response("Invalid CSRF token.", status_code=403)
