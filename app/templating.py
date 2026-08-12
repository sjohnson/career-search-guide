"""Shared Jinja2 templates with CSRF in every response context."""

from fastapi.templating import Jinja2Templates

from app.services.csrf import CSRF_FORM_FIELD, ensure_csrf_token

_templates = Jinja2Templates(directory="app/templates")
_templates.env.globals["csrf_field_name"] = CSRF_FORM_FIELD


class AppTemplates:
    def TemplateResponse(self, request, name: str, context: dict | None = None, **kwargs):
        ctx = dict(context or {})
        ctx.setdefault("csrf_token", ensure_csrf_token(request))
        return _templates.TemplateResponse(request, name, ctx, **kwargs)


templates = AppTemplates()
