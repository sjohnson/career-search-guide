"""Tests for app.utils.

`utcnow()` looks like a one-liner that anyone could "clean up" later — dropping
the `.replace(tzinfo=None)` to return a proper aware datetime, or swapping in
`datetime.now()` because it reads more simply. Both changes break the app in
ways that are easy to miss locally, so each is pinned by a test here.
"""

import os
import time
from datetime import datetime, timezone

import pytest

from app.database import SessionLocal
from app.models import Opportunity
from app.utils import utcnow


@pytest.fixture
def non_utc_timezone():
    """Run the test under a local zone that is never equal to UTC.

    Without this, a `datetime.now()` regression would pass on any machine
    already set to UTC — including most CI runners.
    """
    if not hasattr(time, "tzset"):
        pytest.skip("time.tzset() is Unix-only")

    original = os.environ.get("TZ")
    os.environ["TZ"] = "America/Denver"  # UTC-6/-7 year round
    time.tzset()
    yield
    if original is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = original
    time.tzset()


class TestUtcnow:
    def test_returns_naive_datetime(self):
        """Every DateTime column in app.models is naive, and SQLite stores
        naive values. An aware return value would raise TypeError on any
        comparison against a stored timestamp."""
        assert utcnow().tzinfo is None

    def test_returns_utc_not_local_time(self, non_utc_timezone):
        result = utcnow()

        assert abs((result - datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds()) < 5
        # Denver runs 6-7 hours behind UTC, so a result anywhere near local
        # time means the function is reading the system clock's zone.
        assert abs((result - datetime.now()).total_seconds()) > 3600

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
