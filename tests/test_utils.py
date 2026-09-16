"""Tests for app.utils.

`utcnow()` looks like a one-liner that anyone could "clean up" later — dropping
the `.replace(tzinfo=None)` to return a proper aware datetime, or swapping in
`datetime.now()` because it reads more simply. Both changes break the app in
ways that are easy to miss locally, so each is pinned by a test here.
"""

from datetime import datetime, timezone

import app.utils
from app.database import SessionLocal
from app.models import Opportunity
from app.utils import utcnow


class FrozenDatetime:
    """Stand-in for `datetime` that reports different times for UTC and local.

    Lets the test tell whether `utcnow()` asked for UTC or just read the
    system clock's zone, without depending on `time.tzset()` — which mise's
    Python 3.13 build does not provide on macOS.
    """

    UTC = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    LOCAL = datetime(2026, 1, 1, 5, 0, 0)  # the same instant, Denver-style

    @classmethod
    def now(cls, tz=None):
        return cls.LOCAL if tz is None else cls.UTC.astimezone(tz)


class TestUtcnow:
    def test_returns_naive_datetime(self):
        """Every DateTime column in app.models is naive, and SQLite stores
        naive values. An aware return value would raise TypeError on any
        comparison against a stored timestamp."""
        assert utcnow().tzinfo is None

    def test_returns_utc_not_local_time(self, monkeypatch):
        monkeypatch.setattr(app.utils, "datetime", FrozenDatetime)

        assert utcnow() == datetime(2026, 1, 1, 12, 0, 0)

    def test_is_comparable_with_a_stored_timestamp(self):
        """The failure this helper exists to prevent: arithmetic against a
        value that has made a round trip through the database."""
        db = SessionLocal()
        try:
            opp = Opportunity(company="utcnow comparability check")
            db.add(opp)
            db.commit()
            db.refresh(opp)

            # Raises TypeError if either side is timezone-aware.
            age = utcnow() - opp.created_at
        finally:
            db.close()

        assert age.total_seconds() >= 0
