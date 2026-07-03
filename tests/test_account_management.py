import json
import inspect
import sqlite3
import tempfile
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.telegram_accounts.models import Proxy, TelegramAccount


def valid_session_bytes():
    with tempfile.NamedTemporaryFile(suffix=".session") as temp_file:
        with sqlite3.connect(temp_file.name) as conn:
            conn.execute("CREATE TABLE version (number INTEGER)")
            conn.execute(
                "CREATE TABLE sessions (dc_id INTEGER PRIMARY KEY, api_id INTEGER, test_mode INTEGER, auth_key BLOB, date INTEGER, user_id INTEGER, is_bot INTEGER)"
            )
            conn.execute("INSERT INTO version VALUES (4)")
            conn.execute("INSERT INTO sessions VALUES (1, 12345, 0, ?, 1, 777, 0)", (b"auth-key",))
            conn.commit()
        temp_file.seek(0)
        return temp_file.read()


def fake_run_auth_flow_operation(account, operation, *, reset=False):
    if operation.__name__ == "send_code_operation":
        return SimpleNamespace(phone_code_hash=f"hash-{account.phone_number}", timeout=180)

    closure = inspect.getclosurevars(operation).nonlocals
    verification_code = closure.get("verification_code", "")
    password_2fa = closure.get("password_2fa", "")

    if verification_code == "12345" and not password_2fa:
        return {
            "auth_state": TelegramAccount.AuthState.PENDING_2FA,
            "last_auth_error": "2FA password required.",
            "requires_2fa": True,
        }

    return SimpleNamespace(id=777, username="farmuser", first_name="Farm", last_name="User")


def fake_invalid_code_operation(account, operation, *, reset=False):
    from pyrogram.errors import BadRequest

    if operation.__name__ == "send_code_operation":
        return SimpleNamespace(phone_code_hash=f"hash-{account.phone_number}", timeout=180)
    raise BadRequest("PHONE_CODE_INVALID")


@pytest.mark.django_db
def test_accounts_overview_supports_session_authenticated_dashboard_calls():
    user = get_user_model().objects.create_user(email="overview@example.com", password="pass")
    TelegramAccount.objects.create(
        owner=user,
        label="Overview Farm",
        phone_number="+380001112233",
        session_name="overview-farm",
        source=TelegramAccount.ConnectSource.CREDENTIALS,
        auth_state=TelegramAccount.AuthState.CONNECTED,
        status=TelegramAccount.Status.ACTIVE,
    )
    client = Client()
    client.force_login(user)

    response = client.get("/api/v1/accounts/overview/")

    assert response.status_code == 200
    assert response.json()["account_count"] == 1
    assert response.json()["connected_count"] == 1


@pytest.mark.django_db
def test_attach_account_via_session_endpoint_creates_attached_account():
    def fake_session_verify(account, operation):
        return SimpleNamespace(id=778, username="sessionuser", first_name="Session", last_name="User")

    user = get_user_model().objects.create_user(email="session@example.com", password="pass")
    proxy = Proxy.objects.create(
        owner=user,
        name="Session Proxy",
        protocol=Proxy.Protocol.SOCKS5,
        host="127.0.0.1",
        port=1080,
    )
    client = Client()
    client.force_login(user)
    from apps.telegram_accounts import services
    original = services.run_client_operation
    services.run_client_operation = fake_session_verify

    try:
        response = client.post(
            "/api/v1/accounts/add/",
            {
                "attach_mode": TelegramAccount.ConnectSource.SESSION,
                "label": "Session Import",
                "phone_number": "+380991112233",
                "proxy": proxy.id,
                "session_file": SimpleUploadedFile("import.session", valid_session_bytes()),
            },
        )
    finally:
        services.run_client_operation = original

    assert response.status_code == 201
    account = TelegramAccount.objects.get(owner=user, label="Session Import")
    assert account.is_attached is True
    assert account.source == TelegramAccount.ConnectSource.SESSION
    assert account.auth_state == TelegramAccount.AuthState.CONNECTED
    assert account.status == TelegramAccount.Status.ACTIVE


@pytest.mark.django_db
def test_attach_account_via_session_rejects_non_sqlite_file():
    user = get_user_model().objects.create_user(email="bad-session@example.com", password="pass")
    client = Client()
    client.force_login(user)

    response = client.post(
        "/api/v1/accounts/add/",
        {
            "attach_mode": TelegramAccount.ConnectSource.SESSION,
            "label": "Bad Session",
            "session_file": SimpleUploadedFile("import.session", b"not sqlite"),
        },
    )

    assert response.status_code == 400
    assert not TelegramAccount.objects.filter(owner=user, label="Bad Session").exists()


@pytest.mark.django_db
def test_credentials_attach_rejects_invalid_phone_number():
    user = get_user_model().objects.create_user(email="bad-phone@example.com", password="pass")
    client = Client()
    client.force_login(user)

    response = client.post(
        "/api/v1/accounts/add/",
        {
            "attach_mode": TelegramAccount.ConnectSource.CREDENTIALS,
            "label": "Bad Phone",
            "phone_number": "not-a-phone",
        },
    )

    assert response.status_code == 400
    assert not TelegramAccount.objects.filter(owner=user, label="Bad Phone").exists()


@pytest.mark.django_db
def test_credentials_auth_flow_handles_pending_2fa_then_connects(monkeypatch):
    monkeypatch.setattr(
        "apps.telegram_accounts.services.run_auth_flow_operation",
        fake_run_auth_flow_operation,
    )
    monkeypatch.setattr(
        "apps.telegram_accounts.services.refresh_account_profile_snapshot",
        lambda account: account,
    )
    user = get_user_model().objects.create_user(email="credentials@example.com", password="pass")
    client = Client()
    client.force_login(user)

    create_response = client.post(
        "/api/v1/accounts/add/",
        {
            "attach_mode": TelegramAccount.ConnectSource.CREDENTIALS,
            "label": "2FA Account",
            "phone_number": "+380671112233",
            "requires_2fa": "true",
        },
    )

    assert create_response.status_code == 201
    account_id = create_response.json()["id"]
    assert create_response.json()["auth_state"] == TelegramAccount.AuthState.PENDING_CODE

    step_one = client.post(
        f"/api/v1/accounts/{account_id}/complete-auth/",
        data=json.dumps({"verification_code": "12345"}),
        content_type="application/json",
    )
    assert step_one.status_code == 200
    assert step_one.json()["auth_state"] == TelegramAccount.AuthState.PENDING_2FA

    step_two = client.post(
        f"/api/v1/accounts/{account_id}/complete-auth/",
        data=json.dumps({"verification_code": "", "password_2fa": "top-secret"}),
        content_type="application/json",
    )
    assert step_two.status_code == 200
    assert step_two.json()["auth_state"] == TelegramAccount.AuthState.CONNECTED
    assert step_two.json()["status"] == TelegramAccount.Status.ACTIVE


@pytest.mark.django_db
def test_bulk_detach_endpoint_detaches_multiple_accounts():
    user = get_user_model().objects.create_user(email="detach@example.com", password="pass")
    account_a = TelegramAccount.objects.create(
        owner=user,
        label="Detach A",
        session_name="detach-a",
        auth_state=TelegramAccount.AuthState.CONNECTED,
        status=TelegramAccount.Status.ACTIVE,
    )
    account_b = TelegramAccount.objects.create(
        owner=user,
        label="Detach B",
        session_name="detach-b",
        auth_state=TelegramAccount.AuthState.CONNECTED,
        status=TelegramAccount.Status.ACTIVE,
    )
    client = Client()
    client.force_login(user)

    response = client.post(
        "/api/v1/accounts/detach/",
        data=json.dumps({"account_ids": [account_a.id, account_b.id]}),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["detached_count"] == 2
    account_a.refresh_from_db()
    account_b.refresh_from_db()
    assert account_a.is_attached is False
    assert account_b.auth_state == TelegramAccount.AuthState.DETACHED


@pytest.mark.django_db
def test_assign_proxy_endpoint_updates_single_account_proxy():
    user = get_user_model().objects.create_user(email="assign-proxy@example.com", password="pass")
    proxy = Proxy.objects.create(
        owner=user,
        name="Mobile Proxy",
        protocol=Proxy.Protocol.SOCKS5,
        host="127.0.0.1",
        port=1080,
    )
    account = TelegramAccount.objects.create(
        owner=user,
        label="Proxy Target",
        session_name="proxy-target",
        auth_state=TelegramAccount.AuthState.CONNECTED,
        status=TelegramAccount.Status.ACTIVE,
    )
    client = Client()
    client.force_login(user)

    response = client.post(
        f"/api/v1/accounts/{account.id}/proxy/",
        data=json.dumps({"proxy": proxy.id}),
        content_type="application/json",
    )

    assert response.status_code == 200
    account.refresh_from_db()
    assert account.proxy == proxy


@pytest.mark.django_db
def test_assign_proxy_endpoint_rejects_proxy_owned_by_another_user():
    owner = get_user_model().objects.create_user(email="assign-own-proxy@example.com", password="pass")
    other = get_user_model().objects.create_user(email="assign-other-proxy@example.com", password="pass")
    proxy = Proxy.objects.create(
        owner=other,
        name="Other Proxy",
        protocol=Proxy.Protocol.SOCKS5,
        host="127.0.0.1",
        port=1080,
    )
    account = TelegramAccount.objects.create(
        owner=owner,
        label="Own Account",
        session_name="own-account",
        auth_state=TelegramAccount.AuthState.CONNECTED,
        status=TelegramAccount.Status.ACTIVE,
    )
    client = Client()
    client.force_login(owner)

    response = client.post(
        f"/api/v1/accounts/{account.id}/proxy/",
        data=json.dumps({"proxy": proxy.id}),
        content_type="application/json",
    )

    assert response.status_code == 400
    account.refresh_from_db()
    assert account.proxy is None


@pytest.mark.django_db
def test_resend_code_endpoint_restores_pending_code_state(monkeypatch):
    monkeypatch.setattr(
        "apps.telegram_accounts.services.run_auth_flow_operation",
        fake_run_auth_flow_operation,
    )
    user = get_user_model().objects.create_user(email="resend@example.com", password="pass")
    account = TelegramAccount.objects.create(
        owner=user,
        label="Resend Me",
        phone_number="+380671112244",
        session_name="resend-me",
        source=TelegramAccount.ConnectSource.CREDENTIALS,
        auth_state=TelegramAccount.AuthState.FAILED,
        auth_phone_code_hash="old-hash",
        last_auth_error="Telegram says: [400 PHONE_CODE_EXPIRED]",
    )
    client = Client()
    client.force_login(user)

    response = client.post(
        f"/api/v1/accounts/{account.id}/resend-code/",
        data=json.dumps({}),
        content_type="application/json",
    )

    assert response.status_code == 200
    account.refresh_from_db()
    assert account.auth_state == TelegramAccount.AuthState.PENDING_CODE
    assert account.auth_phone_code_hash == "hash-+380671112244"
    assert account.last_auth_error == ""


@pytest.mark.django_db
def test_missing_verification_code_keeps_pending_code_state(monkeypatch):
    monkeypatch.setattr(
        "apps.telegram_accounts.services.run_auth_flow_operation",
        fake_run_auth_flow_operation,
    )
    user = get_user_model().objects.create_user(email="nocode@example.com", password="pass")
    account = TelegramAccount.objects.create(
        owner=user,
        label="Pending Code",
        phone_number="+380671112255",
        session_name="pending-code",
        source=TelegramAccount.ConnectSource.CREDENTIALS,
        auth_state=TelegramAccount.AuthState.PENDING_CODE,
        auth_phone_code_hash="pending-hash",
    )
    client = Client()
    client.force_login(user)

    response = client.post(
        f"/api/v1/accounts/{account.id}/complete-auth/",
        data=json.dumps({"verification_code": ""}),
        content_type="application/json",
    )

    assert response.status_code == 200
    account.refresh_from_db()
    assert account.auth_state == TelegramAccount.AuthState.PENDING_CODE
    assert account.last_auth_error == "Verification code required."


@pytest.mark.django_db
def test_invalid_verification_code_keeps_pending_code_state(monkeypatch):
    monkeypatch.setattr(
        "apps.telegram_accounts.services.run_auth_flow_operation",
        fake_invalid_code_operation,
    )
    user = get_user_model().objects.create_user(email="invalid-code@example.com", password="pass")
    account = TelegramAccount.objects.create(
        owner=user,
        label="Invalid Code",
        phone_number="+380671112266",
        session_name="invalid-code",
        source=TelegramAccount.ConnectSource.CREDENTIALS,
        auth_state=TelegramAccount.AuthState.PENDING_CODE,
        auth_phone_code_hash="pending-hash",
    )
    client = Client()
    client.force_login(user)

    response = client.post(
        f"/api/v1/accounts/{account.id}/complete-auth/",
        data=json.dumps({"verification_code": "11111"}),
        content_type="application/json",
    )

    assert response.status_code == 200
    account.refresh_from_db()
    assert account.auth_state == TelegramAccount.AuthState.PENDING_CODE
    assert "PHONE_CODE_INVALID" in account.last_auth_error


@pytest.mark.django_db
def test_cleanup_stale_endpoint_deletes_failed_and_detached_accounts():
    user = get_user_model().objects.create_user(email="cleanup@example.com", password="pass")
    failed = TelegramAccount.objects.create(
        owner=user,
        label="Failed",
        session_name="failed-cleanup",
        auth_state=TelegramAccount.AuthState.FAILED,
    )
    detached = TelegramAccount.objects.create(
        owner=user,
        label="Detached",
        session_name="detached-cleanup",
        auth_state=TelegramAccount.AuthState.DETACHED,
    )
    active = TelegramAccount.objects.create(
        owner=user,
        label="Active",
        session_name="active-cleanup",
        auth_state=TelegramAccount.AuthState.CONNECTED,
        status=TelegramAccount.Status.ACTIVE,
    )
    client = Client()
    client.force_login(user)

    response = client.post(
        "/api/v1/accounts/cleanup-stale/",
        data=json.dumps({}),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["deleted_count"] == 2
    assert not TelegramAccount.objects.filter(id__in=[failed.id, detached.id]).exists()
    assert TelegramAccount.objects.filter(id=active.id).exists()


@pytest.mark.django_db
def test_runtime_event_rejects_non_object_metadata():
    user = get_user_model().objects.create_user(email="runtime-metadata@example.com", password="pass")
    account = TelegramAccount.objects.create(owner=user, label="Runtime", session_name="runtime")
    client = Client()
    client.force_login(user)

    response = client.post(
        f"/api/v1/accounts/{account.id}/runtime-events/",
        data=json.dumps({"event_type": "success", "metadata": ["not", "object"]}),
        content_type="application/json",
    )

    assert response.status_code == 400
