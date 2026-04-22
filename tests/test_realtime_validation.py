import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client


@pytest.mark.django_db
def test_publish_log_rejects_empty_message():
    user = get_user_model().objects.create_user(email="logs@example.com", password="pass")
    client = Client()
    client.force_login(user)

    response = client.post(
        "/api/v1/realtime/logs/publish/",
        data=json.dumps({"level": "info", "source": "manual", "message": "   "}),
        content_type="application/json",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_publish_log_rejects_unknown_level():
    user = get_user_model().objects.create_user(email="logs-level@example.com", password="pass")
    client = Client()
    client.force_login(user)

    response = client.post(
        "/api/v1/realtime/logs/publish/",
        data=json.dumps({"level": "fatal", "source": "manual", "message": "hello"}),
        content_type="application/json",
    )

    assert response.status_code == 400
