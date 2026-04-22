import hashlib
import hmac

import pytest
from django.conf import settings
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_telegram_login_issues_tokens(settings):
    settings.TELEGRAM_BOT_TOKEN = "test-token"
    payload = {
        "id": 123456,
        "first_name": "Test",
        "last_name": "User",
        "username": "testuser",
        "auth_date": 1700000000,
    }
    secret = hashlib.sha256(settings.TELEGRAM_BOT_TOKEN.encode("utf-8")).digest()
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(payload.items()))
    payload["hash"] = hmac.new(secret, check_string.encode("utf-8"), hashlib.sha256).hexdigest()

    response = APIClient().post("/api/v1/auth/telegram/", payload, format="json")

    assert response.status_code == 200
    assert "access" in response.data["tokens"]
    assert response.data["user"]["telegram_id"] == 123456

