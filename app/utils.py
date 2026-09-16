from datetime import datetime, timezone


def utcnow() -> datetime:
    """Current UTC time as a naive datetime.

    Replaces the deprecated ``datetime.utcnow()`` (deprecated in Python 3.12;
    this project pins 3.13). The ``tzinfo`` is stripped deliberately: every
    ``DateTime`` column in ``app.models`` is naive, and SQLite stores naive
    values, so returning an aware datetime here would make comparisons against
    stored timestamps raise ``TypeError``.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
