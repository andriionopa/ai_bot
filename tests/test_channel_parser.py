from datetime import datetime, timezone as dt_timezone
from types import SimpleNamespace

import pytest
from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from pyrogram.enums import ChatType
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.channel_parser.models import ChannelCollectionItem, ChannelCollectionTemplate, ChannelParserJob, ChannelParserLog, ParsedChannel
from apps.channel_parser.services import (
    ParserTiming,
    _parse_with_account,
    _safe_attr_text,
    build_search_queries,
    log_parser_event,
    parser_timing,
)
from apps.telegram_accounts.models import TelegramAccount


def auth_client(user):
    token = str(RefreshToken.for_user(user).access_token)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.mark.django_db
def test_channel_parser_job_create_sets_owner_and_accounts():
    user = get_user_model().objects.create_user(email="parser@example.com")
    account = TelegramAccount.objects.create(
        owner=user,
        label="Parser Account",
        session_name="parser-account",
        is_attached=True,
        auth_state=TelegramAccount.AuthState.CONNECTED,
    )

    response = auth_client(user).post(
        "/api/v1/parser/channels/jobs/add/",
        {
            "name": "Business parser",
            "account_ids": [account.id],
            "keywords": ["Бізнес", "Заробіток"],
            "suffixes": ["2026"],
            "result_limit": 50,
            "subscriber_min": 500,
            "subscriber_max": 1000000,
            "rating_min": 5,
            "languages": ["uk", "ru"],
        },
        format="json",
    )

    assert response.status_code == 201
    job = ChannelParserJob.objects.get(pk=response.data["id"])
    assert job.owner == user
    assert list(job.accounts.values_list("id", flat=True)) == [account.id]
    assert build_search_queries(job) == ["Бізнес", "Заробіток", "Бізнес 2026", "Заробіток 2026"]


@pytest.mark.django_db
def test_channel_parser_overview_returns_templates_accounts_and_latest_results():
    user = get_user_model().objects.create_user(email="parser-overview@example.com")
    account = TelegramAccount.objects.create(
        owner=user,
        label="Parser Account",
        session_name="parser-overview-account",
        is_attached=True,
        auth_state=TelegramAccount.AuthState.CONNECTED,
    )
    job = ChannelParserJob.objects.create(owner=user, name="Parser", keywords=["Крипта"])
    job.accounts.add(account)

    response = auth_client(user).get("/api/v1/parser/channels/overview/")

    assert response.status_code == 200
    assert response.data["jobs"][0]["id"] == job.id
    assert response.data["accounts"][0]["id"] == account.id
    assert "business" in response.data["templates"]


@pytest.mark.django_db
def test_export_endpoint_supports_csv_txt_and_json_without_drf_format_conflict():
    user = get_user_model().objects.create_user(email="parser-export@example.com")
    job = ChannelParserJob.objects.create(owner=user, name="Export parser", keywords=["Бізнес"])
    ParsedChannel.objects.create(
        owner=user,
        job=job,
        title="Бізнес трендс",
        username="business_trends",
        url="https://t.me/business_trends",
        subscribers=2500,
        rating=7,
        language="uk",
        activity_level="active",
        comments_open=True,
    )
    client = auth_client(user)

    csv_response = client.get(f"/api/v1/parser/channels/jobs/{job.id}/export/?export_format=csv")
    txt_response = client.get(f"/api/v1/parser/channels/jobs/{job.id}/export/?export_format=txt")
    json_response = client.get(f"/api/v1/parser/channels/jobs/{job.id}/export/?export_format=json")

    assert csv_response.status_code == 200
    assert txt_response.status_code == 200
    assert json_response.status_code == 200
    assert "text/csv" in csv_response["Content-Type"]
    assert "text/plain" in txt_response["Content-Type"]
    assert "application/json" in json_response["Content-Type"]


@pytest.mark.django_db
def test_channel_template_attach_results_creates_named_collection_and_returns_in_overview():
    user = get_user_model().objects.create_user(email="parser-template@example.com")
    job = ChannelParserJob.objects.create(owner=user, name="Business parser", keywords=["Бізнес"])
    result = ParsedChannel.objects.create(
        owner=user,
        job=job,
        title="Бізнес трендс",
        username="business_trends",
        url="https://t.me/business_trends",
        subscribers=5000,
        rating=8,
    )
    client = auth_client(user)

    create_response = client.post(
        "/api/v1/parser/channels/channel-templates/attach-results/",
        {
            "name": "Товарка",
            "job_id": job.id,
            "result_ids": [result.id],
        },
        format="json",
    )
    overview_response = client.get("/api/v1/parser/channels/overview/")

    assert create_response.status_code == 200
    assert ChannelCollectionTemplate.objects.filter(owner=user, name="Товарка").exists()
    assert ChannelCollectionItem.objects.filter(owner=user, template__name="Товарка", username="business_trends").exists()
    assert overview_response.status_code == 200
    assert overview_response.data["channel_templates"][0]["name"] == "Товарка"


@pytest.mark.django_db
def test_channel_template_attach_results_can_append_to_existing_template():
    user = get_user_model().objects.create_user(email="parser-template-append@example.com")
    job = ChannelParserJob.objects.create(owner=user, name="Business parser", keywords=["Бізнес"])
    result_a = ParsedChannel.objects.create(owner=user, job=job, title="A", username="chan_a", url="https://t.me/chan_a")
    result_b = ParsedChannel.objects.create(owner=user, job=job, title="B", username="chan_b", url="https://t.me/chan_b")
    template = ChannelCollectionTemplate.objects.create(owner=user, name="Товарка")
    client = auth_client(user)

    first_response = client.post(
        "/api/v1/parser/channels/channel-templates/attach-results/",
        {"template_id": template.id, "job_id": job.id, "result_ids": [result_a.id]},
        format="json",
    )
    second_response = client.post(
        "/api/v1/parser/channels/channel-templates/attach-results/",
        {"template_id": template.id, "job_id": job.id, "result_ids": [result_b.id]},
        format="json",
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert ChannelCollectionItem.objects.filter(template=template).count() == 2


@pytest.mark.django_db
def test_results_clear_endpoint_deletes_results_for_selected_job():
    user = get_user_model().objects.create_user(email="parser-clear@example.com")
    job = ChannelParserJob.objects.create(owner=user, name="Clear parser", keywords=["Бізнес"])
    ParsedChannel.objects.create(owner=user, job=job, title="A", username="a")
    ParsedChannel.objects.create(owner=user, job=job, title="B", username="b")

    response = auth_client(user).post("/api/v1/parser/channels/results/clear/", {"job_id": job.id}, format="json")

    assert response.status_code == 200
    assert response.data["deleted"] >= 2
    assert ParsedChannel.objects.filter(job=job).count() == 0


@pytest.mark.django_db
def test_account_overview_marks_running_parser_role():
    user = get_user_model().objects.create_user(email="parser-role@example.com")
    account = TelegramAccount.objects.create(
        owner=user,
        label="Parser Role Account",
        session_name="parser-role-account",
        is_attached=True,
        auth_state=TelegramAccount.AuthState.CONNECTED,
    )
    job = ChannelParserJob.objects.create(owner=user, name="Running parser", keywords=["Бізнес"], status=ChannelParserJob.Status.RUNNING)
    job.accounts.add(account)

    response = auth_client(user).get("/api/v1/accounts/overview/")

    assert response.status_code == 200
    account_payload = response.data["accounts"][0]
    assert account_payload["operational_role"] == "parsing"
    assert account_payload["operational_role_label"] == "Парсинг"


def test_parser_timing_clamps_api_protection_delays():
    job = ChannelParserJob(
        name="Timing",
        ai_protection=True,
        speed_mode=ChannelParserJob.SpeedMode.BALANCED,
    )

    timing = parser_timing(job)

    assert timing.request_delay_range == (7.0, 42.0)
    assert timing.channel_delay_range == (7.0, 42.0)
    assert timing.history_limit == 6


@pytest.mark.django_db
def test_parser_log_event_publishes_runtime_payload(monkeypatch):
    user = get_user_model().objects.create_user(email="parser-log@example.com")
    job = ChannelParserJob.objects.create(owner=user, name="Parser", keywords=["Бізнес"])
    published = []

    monkeypatch.setattr("apps.channel_parser.services.publish_log_event", lambda payload: published.append(payload))

    log = log_parser_event(job, level=ChannelParserLog.Level.SUCCESS, message="Знайдено канал")

    assert log.owner == user
    assert published == [
        {
            "level": "success",
            "source": "parser",
            "message": "Знайдено канал",
            "metadata": {"module": "channel_parser", "job_id": job.id, "account_id": None},
        }
    ]


def test_safe_attr_text_ignores_unicode_decode_errors():
    class BrokenText:
        @property
        def title(self):
            raise UnicodeDecodeError("utf-16-le", b"\xff", 0, 1, "unexpected end of data")

    assert _safe_attr_text(BrokenText(), "title") == ""


class FakeParserApp:
    async def search_global(self, query, limit=30):
        yield SimpleNamespace(chat=SimpleNamespace(username="business_trends"))

    async def get_chat(self, chat_ref):
        return SimpleNamespace(
            id=-100123,
            type=ChatType.CHANNEL,
            title="Бізнес трендс",
            username="business_trends",
            members_count=2500,
            description="Український бізнес канал",
            linked_chat=SimpleNamespace(title="Бізнес коментарі"),
        )

    async def get_chat_history(self, chat_id, limit=8):
        for index in range(3):
            yield SimpleNamespace(date=datetime.now(dt_timezone.utc), text=f"Бізнес пост {index}", caption="")


@pytest.mark.django_db(transaction=True)
def test_parse_with_account_uses_async_safe_orm_calls(monkeypatch):
    user = get_user_model().objects.create_user(email="parser-async@example.com")
    account = TelegramAccount.objects.create(owner=user, label="Async Parser", session_name="async-parser")
    job = ChannelParserJob.objects.create(
        owner=user,
        name="Async parser",
        keywords=["Бізнес"],
        search_scope=ChannelParserJob.SearchScope.GLOBAL,
        subscriber_min=100,
        subscriber_max=10000,
        rating_min=1,
        request_delay_seconds=0,
        channel_delay_seconds=0,
    )
    monkeypatch.setattr("apps.channel_parser.services.publish_log_event", lambda payload: None)

    found = async_to_sync(_parse_with_account)(
        FakeParserApp(),
        job,
        account,
        ["Бізнес"],
        ParserTiming(request_delay_range=(0, 0), channel_delay_range=(0, 0), history_limit=3, dialogs_limit=10),
    )

    assert found == 1
    assert ParsedChannel.objects.filter(job=job, username="business_trends").exists()
    assert ChannelParserLog.objects.filter(job=job, level=ChannelParserLog.Level.SUCCESS).exists()


class FakeSubscriptionsApp(FakeParserApp):
    async def search_global(self, query, limit=30):
        raise AssertionError("search_global should not be used in subscriptions mode")

    async def get_dialogs(self, limit=0):
        yield SimpleNamespace(
            chat=SimpleNamespace(
                username="dropship_hub",
                id=-100321,
                type=ChatType.CHANNEL,
                title="Бізнес Telegram Hub",
                description="Канал про бізнес і заробіток",
            )
        )

    async def get_chat(self, chat_ref):
        return SimpleNamespace(
            id=-100321,
            type=ChatType.CHANNEL,
            title="Бізнес Telegram Hub",
            username="dropship_hub",
            members_count=3200,
            description="Канал про бізнес і заробіток",
            linked_chat=SimpleNamespace(title="Hub comments"),
        )


class FakeGroupsApp:
    async def search_global(self, query, limit=30):
        yield SimpleNamespace(chat=SimpleNamespace(username="group_alpha"))

    async def get_chat(self, chat_ref):
        return SimpleNamespace(
            id=-100555,
            type=ChatType.SUPERGROUP,
            title="Group Alpha",
            username="group_alpha",
            members_count=2200,
            description="Business community group",
            linked_chat=None,
        )

    async def get_chat_history(self, chat_id, limit=8):
        for index in range(3):
            yield SimpleNamespace(date=datetime.now(dt_timezone.utc), text=f"group post {index}", caption="")


@pytest.mark.django_db(transaction=True)
def test_parse_with_account_supports_subscription_scope_without_global_search(monkeypatch):
    user = get_user_model().objects.create_user(email="parser-subscriptions@example.com")
    account = TelegramAccount.objects.create(owner=user, label="Sub Parser", session_name="sub-parser")
    job = ChannelParserJob.objects.create(
        owner=user,
        name="Subscriptions parser",
        keywords=["Бізнес Telegram"],
        search_scope=ChannelParserJob.SearchScope.SUBSCRIPTIONS,
        subscriber_min=100,
        subscriber_max=10000,
        rating_min=1,
        request_delay_seconds=0,
        channel_delay_seconds=0,
    )
    monkeypatch.setattr("apps.channel_parser.services.publish_log_event", lambda payload: None)

    found = async_to_sync(_parse_with_account)(
        FakeSubscriptionsApp(),
        job,
        account,
        ["Бізнес Telegram"],
        ParserTiming(request_delay_range=(0, 0), channel_delay_range=(0, 0), history_limit=3, dialogs_limit=10),
    )

    assert found == 1
    assert ParsedChannel.objects.filter(job=job, username="dropship_hub").exists()


@pytest.mark.django_db(transaction=True)
def test_parse_with_account_supports_group_mode(monkeypatch):
    user = get_user_model().objects.create_user(email="parser-groups@example.com")
    account = TelegramAccount.objects.create(owner=user, label="Groups Parser", session_name="groups-parser")
    job = ChannelParserJob.objects.create(
        owner=user,
        name="Groups parser",
        keywords=["Business community"],
        parse_type=ChannelParserJob.ParseType.GROUPS,
        search_scope=ChannelParserJob.SearchScope.GLOBAL,
        subscriber_min=100,
        subscriber_max=10000,
        rating_min=1,
    )
    monkeypatch.setattr("apps.channel_parser.services.publish_log_event", lambda payload: None)

    found = async_to_sync(_parse_with_account)(
        FakeGroupsApp(),
        job,
        account,
        ["Business community"],
        ParserTiming(request_delay_range=(0, 0), channel_delay_range=(0, 0), history_limit=3, dialogs_limit=10),
    )

    result = ParsedChannel.objects.get(job=job, username="group_alpha")
    assert found == 1
    assert result.entity_type == ParsedChannel.EntityType.GROUP
