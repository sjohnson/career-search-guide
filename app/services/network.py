import re
from datetime import date
from urllib.parse import urlparse

from sqlalchemy import case
from sqlalchemy.orm import Query

from app.models import ContactMethod, NetworkContact

METHOD_VALUES = {item.value for item in ContactMethod}

_SPLIT_RE = re.compile(r"[\s,]+")
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def normalize_contact_method(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.strip().lower().replace(" ", "_").replace("-", "_")
    if value in METHOD_VALUES:
        return value
    return None


def clip_text(raw: str | None, max_len: int) -> str | None:
    text = (raw or "").strip()
    if not text:
        return None
    return text[:max_len]


def parse_contact_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def sort_network_contacts(query: Query) -> Query:
    return query.order_by(
        case((NetworkContact.followup_contact_at.is_(None), 1), else_=0),
        NetworkContact.followup_contact_at.asc(),
        NetworkContact.name.asc(),
    )


def _link_label(url: str) -> str:
    try:
        host = (urlparse(url).netloc or "").removeprefix("www.")
    except ValueError:
        return url
    return host or url


def opportunity_link_parts(raw: str | None) -> list[dict]:
    if not raw or not raw.strip():
        return []
    parts = []
    for token in _SPLIT_RE.split(raw.strip()):
        if not token:
            continue
        is_url = bool(_URL_RE.match(token))
        parts.append(
            {
                "text": token,
                "label": _link_label(token) if is_url else token,
                "is_url": is_url,
            }
        )
    return parts
