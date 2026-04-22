import pytest
from django.contrib.auth import get_user_model
from django.test import Client


@pytest.mark.django_db
def test_root_redirects_to_auth_for_anonymous_user():
    response = Client().get("/")
    assert response.status_code == 302
    assert response.headers["Location"] == "/auth/"


@pytest.mark.django_db
def test_dashboard_requires_session_authentication():
    response = Client().get("/dashboard/")
    assert response.status_code == 302
    assert response.headers["Location"].startswith("/auth/")


@pytest.mark.django_db
def test_session_login_redirects_to_dashboard():
    user = get_user_model().objects.create_user(
        email="dash@example.com",
        password="super-secret-pass",
    )
    client = Client()

    response = client.post(
        "/auth/login/",
        {"email": user.email, "password": "super-secret-pass"},
    )

    assert response.status_code == 302
    assert response.headers["Location"] == "/dashboard/"


@pytest.mark.django_db
def test_auth_page_renders_google_button_when_configured(settings):
    settings.GOOGLE_OAUTH_CLIENT_ID = "client-id"
    settings.GOOGLE_OAUTH_CLIENT_SECRET = "client-secret"
    settings.GOOGLE_OAUTH_REDIRECT_URI = "http://127.0.0.1:8000/api/v1/auth/google/callback/"
    settings.TELEGRAM_BOT_USERNAME = "demo_test_bot"

    response = Client().get("/auth/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "Увійти через Google" in content
    assert "telegram-widget.js" in content


@pytest.mark.django_db
def test_google_callback_redirects_browser_to_dashboard(monkeypatch):
    def fake_fetch_google_userinfo(code):
        return {
            "sub": "google-sub-1",
            "email": "google@example.com",
            "name": "Google User",
        }

    monkeypatch.setattr(
        "apps.users.views.fetch_google_userinfo",
        fake_fetch_google_userinfo,
    )

    response = Client().get(
        "/api/v1/auth/google/callback/?code=test-code",
        HTTP_ACCEPT="text/html",
    )

    assert response.status_code == 302
    assert response.headers["Location"] == "/dashboard/"


@pytest.mark.django_db
def test_google_callback_reuses_existing_user_by_email(monkeypatch):
    user = get_user_model().objects.create_user(
        email="google@example.com",
        password="super-secret-pass",
    )

    def fake_fetch_google_userinfo(code):
        return {
            "sub": "google-sub-existing",
            "email": "google@example.com",
            "name": "Google User",
        }

    monkeypatch.setattr(
        "apps.users.views.fetch_google_userinfo",
        fake_fetch_google_userinfo,
    )

    response = Client().get(
        "/api/v1/auth/google/callback/?code=test-code",
        HTTP_ACCEPT="text/html",
    )

    assert response.status_code == 302
    user.refresh_from_db()
    assert user.google_sub == "google-sub-existing"
    assert get_user_model().objects.filter(email="google@example.com").count() == 1


@pytest.mark.django_db
def test_dashboard_renders_farm_controls_for_authenticated_user():
    user = get_user_model().objects.create_user(
        email="farm@example.com",
        password="super-secret-pass",
    )
    client = Client()
    client.force_login(user)

    response = client.get("/dashboard/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "Комбайн" in content
    assert "/dashboard/accounts/add/" in content
    assert "/dashboard/accounts/" in content


@pytest.mark.django_db
def test_account_add_page_requires_authentication():
    response = Client().get("/dashboard/accounts/add/")
    assert response.status_code == 302
    assert response.headers["Location"].startswith("/auth/")


@pytest.mark.django_db
def test_account_status_page_renders_controls_for_authenticated_user():
    user = get_user_model().objects.create_user(
        email="status@example.com",
        password="super-secret-pass",
    )
    client = Client()
    client.force_login(user)

    response = client.get("/dashboard/accounts/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "Статуси акаунтів" in content
    assert "Додати акаунт" in content
    assert "/api/v1/accounts/detach/" in content or "/static/js/farm_pages.js" in content


@pytest.mark.django_db
def test_admin_route_is_not_exposed_anymore():
    response = Client().get("/admin/")
    assert response.status_code == 404
