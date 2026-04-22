import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken


@pytest.mark.django_db
def test_proxy_crud_requires_auth():
    response = APIClient().get("/api/v1/accounts/proxies/")
    assert response.status_code == 401


@pytest.mark.django_db
def test_create_proxy_for_authenticated_user():
    user = get_user_model().objects.create_user(email="owner@example.com")
    token = str(RefreshToken.for_user(user).access_token)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    response = client.post(
        "/api/v1/accounts/proxies/",
        {
            "name": "Primary",
            "protocol": "socks5",
            "host": "127.0.0.1",
            "port": 1080,
            "username": "",
            "password": "",
            "is_active": True,
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.data["name"] == "Primary"


@pytest.mark.django_db
def test_create_proxy_rejects_invalid_port():
    user = get_user_model().objects.create_user(email="bad-port@example.com")
    token = str(RefreshToken.for_user(user).access_token)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    response = client.post(
        "/api/v1/accounts/proxies/",
        {
            "name": "Bad Port",
            "protocol": "socks5",
            "host": "127.0.0.1",
            "port": 70000,
            "username": "",
            "password": "",
            "is_active": True,
        },
        format="json",
    )

    assert response.status_code == 400
