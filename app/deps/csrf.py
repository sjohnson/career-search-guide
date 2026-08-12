"""CSRF validation dependency for mutating routes."""

from fastapi import Form, Request

from app.services.csrf import CSRF_FORM_FIELD, validate_csrf_token


async def verify_csrf(
    request: Request,
    csrf_token: str | None = Form(None, alias=CSRF_FORM_FIELD),
) -> None:
    validate_csrf_token(request, csrf_token)
