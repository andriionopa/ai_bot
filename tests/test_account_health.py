from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.telegram_accounts.models import AccountHealthEvent, TelegramAccount
from apps.telegram_accounts.services import (
    get_account_runtime_block_reason,
    recalculate_account_state,
    register_account_runtime_event,
)


def auth_client(user):
    token = str(RefreshToken.for_user(user).access_token)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.mark.django_db
def test_health_endpoint_returns_account_health_state():
    user = get_user_model().objects.create_user(email="health@example.com")
    account = TelegramAccount.objects.create(
        owner=user,
        label="Farm 1",
        session_name="farm-1",
        status=TelegramAccount.Status.ACTIVE,
    )

    response = auth_client(user).get(f"/api/v1/accounts/{account.id}/health/")

    assert response.status_code == 200
    assert response.data["health_score"] == 100
    assert response.data["status"] == TelegramAccount.Status.ACTIVE
    assert response.data["recommended_pause_range"] == {"min_seconds": 7, "max_seconds": 42}


@pytest.mark.django_db
def test_flood_wait_event_quarantines_account_and_updates_score():
    user = get_user_model().objects.create_user(email="quarantine@example.com")
    account = TelegramAccount.objects.create(
        owner=user,
        label="Farm 2",
        session_name="farm-2",
        status=TelegramAccount.Status.ACTIVE,
    )

    event = register_account_runtime_event(
        account,
        AccountHealthEvent.EventType.FLOOD_WAIT,
        metadata={"seconds": 90},
    )
    account.refresh_from_db()

    assert event.score_delta == -15
    assert account.status == TelegramAccount.Status.QUARANTINE
    assert account.quarantine_until is not None
    assert account.health_score == 85


@pytest.mark.django_db
def test_spam_block_event_quarantines_account_and_updates_score():
    user = get_user_model().objects.create_user(email="spamblock@example.com")
    account = TelegramAccount.objects.create(
        owner=user,
        label="Farm Spam",
        session_name="farm-spam",
        status=TelegramAccount.Status.ACTIVE,
    )

    event = register_account_runtime_event(
        account,
        AccountHealthEvent.EventType.SPAM_BLOCK,
        metadata={"error": "PeerFlood"},
    )
    account.refresh_from_db()

    assert event.score_delta == -30
    assert account.status == TelegramAccount.Status.QUARANTINE
    assert account.quarantine_until is not None
    assert account.health_score == 70


@pytest.mark.django_db
def test_runtime_block_reason_stops_quarantined_account():
    user = get_user_model().objects.create_user(email="blocked-runtime@example.com")
    account = TelegramAccount.objects.create(
        owner=user,
        label="Blocked Farm",
        session_name="blocked-farm",
        auth_state=TelegramAccount.AuthState.CONNECTED,
        status=TelegramAccount.Status.QUARANTINE,
        quarantine_until=timezone.now() + timedelta(hours=1),
    )

    assert "quarantined" in get_account_runtime_block_reason(account)


@pytest.mark.django_db
def test_success_event_is_accepted_via_runtime_events_endpoint():
    user = get_user_model().objects.create_user(email="runtime@example.com")
    account = TelegramAccount.objects.create(
        owner=user,
        label="Farm 3",
        session_name="farm-3",
        status=TelegramAccount.Status.ACTIVE,
    )

    response = auth_client(user).post(
        f"/api/v1/accounts/{account.id}/runtime-events/",
        {"event_type": AccountHealthEvent.EventType.SUCCESS, "metadata": {"source": "worker"}},
        format="json",
    )

    assert response.status_code in {201, 202}
    assert response.data["mode"] in {"sync", "async"}


@pytest.mark.django_db
def test_expired_quarantine_releases_account_back_to_active():
    user = get_user_model().objects.create_user(email="release@example.com")
    account = TelegramAccount.objects.create(
        owner=user,
        label="Farm 4",
        session_name="farm-4",
        status=TelegramAccount.Status.QUARANTINE,
        quarantine_until=timezone.now() - timedelta(minutes=5),
        health_score=50,
    )

    recalculate_account_state(account)
    account.refresh_from_db()

    assert account.status == TelegramAccount.Status.ACTIVE
    assert account.quarantine_until is None
