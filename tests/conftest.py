import os
import re

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest")

from app.main import app  # noqa: E402


def csrf_from_html(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "CSRF token input not found in HTML"
    return match.group(1)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
