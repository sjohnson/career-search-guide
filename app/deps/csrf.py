"""CSRF validation dependency for mutating routes.

Reads the token from the request as a normal form field, which participates in
the endpoint's single body parse — unlike middleware that calls request.form()
and consumes the body before the route can read it.
"""

from fastapi import Form, Request

from app.services.csrf import CSRF_FORM_FIELD, validate_csrf_token

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


async def verify_csrf(
    request: Request,
    csrf_token: str | None = Form(None, alias=CSRF_FORM_FIELD),
) -> None:
    if request.method in SAFE_METHODS:
        return
    validate_csrf_token(request, csrf_token)
