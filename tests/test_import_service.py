from datetime import date, datetime

from app.services.import_service import _parse_bool, _parse_date, _parse_int


class TestParseDate:
    def test_iso_format(self):
        assert _parse_date("2026-01-15") == date(2026, 1, 15)

    def test_us_format(self):
        assert _parse_date("01/15/2026") == date(2026, 1, 15)

    def test_datetime_object(self):
        assert _parse_date(datetime(2026, 1, 15, 12, 30)) == date(2026, 1, 15)

    def test_blank_returns_none(self):
        assert _parse_date(None) is None
        assert _parse_date("") is None


class TestParseBool:
    def test_truthy_values(self):
        assert _parse_bool("yes") is True
        assert _parse_bool("Done") is True
        assert _parse_bool("1") is True

    def test_falsy_values(self):
        assert _parse_bool(None) is False
        assert _parse_bool("no") is False


class TestParseInt:
    def test_valid_integer(self):
        assert _parse_int("42") == 42

    def test_invalid_uses_default(self):
        assert _parse_int("abc", default=7) == 7

    def test_blank_uses_default(self):
        assert _parse_int(None, default=3) == 3
