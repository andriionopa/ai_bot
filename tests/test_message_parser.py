import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.channel_parser.models import ChannelCollectionItem, ChannelCollectionTemplate
from apps.message_parser.models import MessageParserJob, ParsedUser
from apps.message_parser.services import parser_timing
from apps.telegram_accounts.models import TelegramAccount


def auth_client(user):
    token = str(RefreshToken.for_user(user).access_token)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.mark.django_db
def test_message_parser_job_create_sets_owner_and_accounts():
    user = get_user_model().objects.create_user(email="message-parser@example.com")
    account = TelegramAccount.objects.create(
        owner=user,
        label="Parser Account",
        session_name="message-parser-account",
        is_attached=True,
        auth_state=TelegramAccount.AuthState.CONNECTED,
    )

    response = auth_client(user).post(
        "/api/v1/parser/messages/jobs/add/",
        {
            "name": "Users parser",
            "account_ids": [account.id],
            "sources": ["@group_one", "https://t.me/group_two"],
            "keywords": ["крипта"],
            "message_limit": 500,
            "days_limit": 30,
        },
        format="json",
    )

    assert response.status_code == 201
    job = MessageParserJob.objects.get(pk=response.data["id"])
    assert job.owner == user
    assert list(job.accounts.values_list("id", flat=True)) == [account.id]
    assert job.sources == ["@group_one", "https://t.me/group_two"]


@pytest.mark.django_db
def test_message_parser_overview_returns_channel_templates_and_accounts():
    user = get_user_model().objects.create_user(email="message-parser-overview@example.com")
    account = TelegramAccount.objects.create(
        owner=user,
        label="Parser Account",
        session_name="message-parser-overview-account",
        is_attached=True,
        auth_state=TelegramAccount.AuthState.CONNECTED,
    )
    template = ChannelCollectionTemplate.objects.create(owner=user, name="Товарка")
    ChannelCollectionItem.objects.create(owner=user, template=template, title="Chat A", username="chat_a", url="https://t.me/chat_a")
    job = MessageParserJob.objects.create(owner=user, name="Parser", sources=["@chat_a"])
    job.accounts.add(account)

    response = auth_client(user).get("/api/v1/parser/messages/overview/")

    assert response.status_code == 200
    assert response.data["jobs"][0]["id"] == job.id
    assert response.data["accounts"][0]["id"] == account.id
    assert response.data["channel_templates"][0]["name"] == "Товарка"


@pytest.mark.django_db
def test_message_parser_export_endpoint_supports_csv_txt_and_json():
    user = get_user_model().objects.create_user(email="message-parser-export@example.com")
    job = MessageParserJob.objects.create(owner=user, name="Export parser", sources=["@chat"])
    ParsedUser.objects.create(
        owner=user,
        job=job,
        source_ref="@chat",
        source_title="Chat A",
        telegram_user_id=123,
        username="user_a",
        full_name="User A",
        profile_url="https://t.me/user_a",
        message_count=7,
    )
    client = auth_client(user)

    csv_response = client.get(f"/api/v1/parser/messages/jobs/{job.id}/export/?export_format=csv")
    txt_response = client.get(f"/api/v1/parser/messages/jobs/{job.id}/export/?export_format=txt")
    json_response = client.get(f"/api/v1/parser/messages/jobs/{job.id}/export/?export_format=json")

    assert csv_response.status_code == 200
    assert txt_response.status_code == 200
    assert json_response.status_code == 200
    assert "text/csv" in csv_response["Content-Type"]
    assert "text/plain" in txt_response["Content-Type"]
    assert "application/json" in json_response["Content-Type"]


def test_message_parser_timing_uses_ai_protection_ranges():
    job = MessageParserJob(name="Timing", ai_protection=True, speed_mode=MessageParserJob.SpeedMode.BALANCED)

    timing = parser_timing(job)

    assert timing.request_delay_range == (7.0, 42.0)
    assert timing.source_delay_range == (7.0, 42.0)
