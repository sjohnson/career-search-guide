"""Require a logged-in user for all non-public routes."""

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

LOGIN_PATH = "/login"
PUBLIC_PATHS = frozenset({"/login", "/register", "/logout"})


async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if path.startswith("/static") or path in PUBLIC_PATHS:
        return await call_next(request)

    if not request.session.get("user_id"):
        if request.headers.get("HX-Request") == "true":
            return Response(status_code=401, headers={"HX-Redirect": LOGIN_PATH})
        return RedirectResponse(url=LOGIN_PATH, status_code=303)

    return await call_next(request)
