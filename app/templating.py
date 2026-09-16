"""Shared Jinja2 templates with CSRF in every response context."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.services.csrf import CSRF_FORM_FIELD, ensure_csrf_token

_STATIC_DIR = Path(__file__).resolve().parent / "static"


def asset_url(path: str) -> str:
    """Static asset URL stamped with the file's mtime.

    StaticFiles sends no Cache-Control, so browsers fall back to heuristic
    caching and happily serve a stale stylesheet after an edit — which looks
    exactly like CSS that "doesn't work". The mtime query makes every change a
    new URL. Falls back to the bare path if the file is missing, so a typo
    breaks visibly rather than raising during render.
    """
    asset = _STATIC_DIR / path
    try:
        return f"/static/{path}?v={int(asset.stat().st_mtime)}"
    except OSError:
        return f"/static/{path}"


_templates = Jinja2Templates(directory="app/templates")
_templates.env.globals["csrf_field_name"] = CSRF_FORM_FIELD
_templates.env.globals["asset_url"] = asset_url


class AppTemplates:
    def TemplateResponse(self, request, name: str, context: dict | None = None, **kwargs):
        ctx = dict(context or {})
        ctx.setdefault("csrf_token", ensure_csrf_token(request))
        return _templates.TemplateResponse(request, name, ctx, **kwargs)


templates = AppTemplates()
