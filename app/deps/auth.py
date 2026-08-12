"""FastAPI dependencies for authentication."""

from fastapi import Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.database import get_db
from app.models import User
from app.services.auth import get_user_by_id

LOGIN_PATH = "/login"


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return get_user_by_id(db, int(user_id))


def require_user(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user:
        return user

    if _is_htmx(request):
        return Response(
            status_code=401,
            headers={"HX-Redirect": LOGIN_PATH},
        )

    return RedirectResponse(url=LOGIN_PATH, status_code=303)
