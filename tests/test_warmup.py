import asyncio
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone
from pyrogram import raw

from apps.telegram_accounts.models import AccountHealthEvent, TelegramAccount
from apps.telegram_accounts.tasks import register_account_runtime_event_task
from apps.warmup.models import WarmupAction, WarmupLog, WarmupPlan, WarmupPolicy, WarmupTarget
from apps.warmup.services import execute_warmup_action, next_active_time
from apps.warmup.services import (
    _extract_addlist_slug,
    _forward_message_operation,
    _join_chatlist_invite_operation,
    _passive_scan_operation,
    _result_details,
    _view_dialogs_operation,
)
from apps.warmup.tasks import execute_warmup_action_task


@pytest.mark.django_db
def test_warmup_dashboard_requires_authenticated_user():
    response = Client().get("/dashboard/warmup/")

    assert response.status_code == 302
    assert response.headers["Location"].startswith("/auth/")


@pytest.mark.django_db
def test_create_warmup_policy_target_plan_and_start(monkeypatch):
    monkeypatch.setattr("apps.warmup.services.schedule_action_dispatch", lambda action: None)
    user = get_user_model().objects.create_user(email="warmup@example.com", password="pass")
    account = TelegramAccount.objects.create(
        owner=user,
        label="Warm Account",
        session_name="warm-account",
        auth_state=TelegramAccount.AuthState.CONNECTED,
        status=TelegramAccount.Status.ACTIVE,
    )
    client = Client()
    client.force_login(user)

    policy_response = client.post(
        "/api/v1/warmup/policies/add/",
        data=json.dumps(
            {
                "name": "Safe warmup",
                "behavior_profile": "safe",
                "daily_join_min": 1,
                "daily_join_max": 1,
                "delay_min_seconds": 60,
                "delay_max_seconds": 60,
                "read_min_seconds": 1,
                "read_max_seconds": 2,
                "reaction_probability": 0,
                "max_reactions_per_day": 0,
                "retry_min_seconds": 60,
                "retry_max_seconds": 120,
                "active_start_hour": 0,
                "active_end_hour": 23,
                "allow_folder_one_click": False,
                "allow_private_join": True,
            }
        ),
        content_type="application/json",
    )
    assert policy_response.status_code == 201

    target_response = client.post(
        "/api/v1/warmup/targets/add/",
        data=json.dumps(
            {
                "title": "Target UA",
                "target_type": "channel",
                "visibility": "public",
                "value": "@target_ua",
            }
        ),
        content_type="application/json",
    )
    assert target_response.status_code == 201

    plan_response = client.post(
        "/api/v1/warmup/plans/add/",
        data=json.dumps(
            {
                "name": "Batch 01",
                "policy": policy_response.json()["id"],
                "account_ids": [account.id],
                "target_ids": [target_response.json()["id"]],
            }
        ),
        content_type="application/json",
    )
    assert plan_response.status_code == 201, plan_response.json()

    start_response = client.post(f"/api/v1/warmup/plans/{plan_response.json()['id']}/start/")
    assert start_response.status_code == 200
    assert start_response.json()["status"] == WarmupPlan.Status.RUNNING
    assert WarmupAction.objects.filter(plan_id=plan_response.json()["id"], action_type=WarmupAction.ActionType.JOIN_CHANNEL).exists()
    assert WarmupAction.objects.filter(plan_id=plan_response.json()["id"], action_type=WarmupAction.ActionType.READ).exists()


@pytest.mark.django_db
def test_warmup_plan_rejects_unconnected_account():
    user = get_user_model().objects.create_user(email="warmup-invalid@example.com", password="pass")
    account = TelegramAccount.objects.create(
        owner=user,
        label="Draft Account",
        session_name="draft-account",
        auth_state=TelegramAccount.AuthState.PENDING_CODE,
        status=TelegramAccount.Status.DRAFT,
    )
    policy = WarmupPolicy.objects.create(owner=user, name="Safe", daily_join_min=1, daily_join_max=1)
    target = WarmupTarget.objects.create(owner=user, title="Target", value="@target_ua")
    client = Client()
    client.force_login(user)

    response = client.post(
        "/api/v1/warmup/plans/add/",
        data=json.dumps({"name": "Bad", "policy": policy.id, "account_ids": [account.id], "target_ids": [target.id]}),
        content_type="application/json",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_bulk_import_warmup_targets_accepts_comma_and_newline_list():
    user = get_user_model().objects.create_user(email="warmup-bulk@example.com", password="pass")
    client = Client()
    client.force_login(user)

    response = client.post(
        "/api/v1/warmup/targets/bulk-import/",
        data=json.dumps(
            {
                "targets": "@channel_one, https://t.me/channel_two\n@channel_one",
                "visibility": "public",
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 201
    assert response.json()["created_count"] == 2
    assert response.json()["skipped_count"] == 0
    assert WarmupTarget.objects.filter(owner=user).count() == 2


@pytest.mark.django_db
def test_bulk_import_warmup_targets_rejects_invalid_item():
    user = get_user_model().objects.create_user(email="warmup-bulk-invalid@example.com", password="pass")
    client = Client()
    client.force_login(user)

    response = client.post(
        "/api/v1/warmup/targets/bulk-import/",
        data=json.dumps({"targets": "@valid_channel, javascript:alert(1)", "visibility": "public"}),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert not WarmupTarget.objects.filter(owner=user).exists()


@pytest.mark.django_db
def test_warmup_policy_schedules_extended_scenario_actions(monkeypatch):
    monkeypatch.setattr("apps.warmup.services.schedule_action_dispatch", lambda action: None)
    user = get_user_model().objects.create_user(email="warmup-scenarios@example.com", password="pass")
    account = TelegramAccount.objects.create(
        owner=user,
        label="Scenario Account",
        session_name="scenario-account",
        auth_state=TelegramAccount.AuthState.CONNECTED,
        status=TelegramAccount.Status.ACTIVE,
    )
    policy = WarmupPolicy.objects.create(
        owner=user,
        name="Full scenario",
        daily_join_min=1,
        daily_join_max=1,
        delay_min_seconds=60,
        delay_max_seconds=60,
        read_min_seconds=1,
        read_max_seconds=2,
        reaction_probability=0,
        enable_message_search=True,
        enable_video_scan=True,
        enable_gif_search=True,
        enable_inline_bot_check=True,
        enable_profile_view=True,
        search_query="crypto",
    )
    target = WarmupTarget.objects.create(owner=user, title="Target", value="@target_ua")
    plan = WarmupPlan.objects.create(owner=user, name="Plan", policy=policy)
    plan.accounts.add(account)
    plan.targets.add(target)

    from apps.warmup.services import start_warmup_plan

    start_warmup_plan(plan)

    action_types = set(WarmupAction.objects.filter(plan=plan).values_list("action_type", flat=True))
    assert WarmupAction.ActionType.MESSAGE_SEARCH in action_types
    assert WarmupAction.ActionType.VIDEO_SCAN in action_types
    assert WarmupAction.ActionType.GIF_SEARCH in action_types
    assert WarmupAction.ActionType.INLINE_BOT_CHECK in action_types
    assert WarmupAction.ActionType.PROFILE_VIEW in action_types
    assert not WarmupLog.objects.filter(plan=plan, message__contains="План").exists()


@pytest.mark.django_db
def test_execute_warmup_action_skips_quarantined_account():
    user = get_user_model().objects.create_user(email="warmup-skip@example.com", password="pass")
    account = TelegramAccount.objects.create(
        owner=user,
        label="Quarantine",
        session_name="quarantine",
        auth_state=TelegramAccount.AuthState.CONNECTED,
        status=TelegramAccount.Status.QUARANTINE,
        quarantine_until=timezone.now() + timedelta(hours=1),
    )
    policy = WarmupPolicy.objects.create(owner=user, name="Safe", daily_join_min=1, daily_join_max=1)
    target = WarmupTarget.objects.create(owner=user, title="Target", value="@target_ua")
    plan = WarmupPlan.objects.create(owner=user, name="Plan", policy=policy, status=WarmupPlan.Status.RUNNING)
    plan.accounts.add(account)
    plan.targets.add(target)
    action = WarmupAction.objects.create(
        owner=user,
        plan=plan,
        account=account,
        target=target,
        action_type=WarmupAction.ActionType.READ,
        scheduled_for=timezone.now(),
    )

    action = execute_warmup_action(action.id)

    assert action.status == WarmupAction.Status.SKIPPED
    assert "quarantined" in action.error
    assert WarmupLog.objects.filter(action=action, level=WarmupLog.Level.WARNING).exists()


@pytest.mark.django_db
def test_execute_warmup_action_success_updates_health(monkeypatch):
    user = get_user_model().objects.create_user(email="warmup-run@example.com", password="pass")
    account = TelegramAccount.objects.create(
        owner=user,
        label="Runner",
        session_name="runner",
        auth_state=TelegramAccount.AuthState.CONNECTED,
        status=TelegramAccount.Status.ACTIVE,
    )
    policy = WarmupPolicy.objects.create(owner=user, name="Safe", daily_join_min=1, daily_join_max=1)
    target = WarmupTarget.objects.create(owner=user, title="Target", value="@target_ua")
    plan = WarmupPlan.objects.create(owner=user, name="Plan", policy=policy, status=WarmupPlan.Status.RUNNING)
    plan.accounts.add(account)
    plan.targets.add(target)
    action = WarmupAction.objects.create(
        owner=user,
        plan=plan,
        account=account,
        target=target,
        action_type=WarmupAction.ActionType.JOIN_CHANNEL,
        scheduled_for=timezone.now(),
    )
    monkeypatch.setattr("apps.warmup.services.run_client_operation", lambda account, operation: {"ok": True})

    action = execute_warmup_action(action.id)

    assert action.status == WarmupAction.Status.SUCCEEDED
    assert AccountHealthEvent.objects.filter(account=account, event_type=AccountHealthEvent.EventType.SUCCESS).exists()
    assert WarmupLog.objects.filter(action=action, level=WarmupLog.Level.SUCCESS, message__contains="✅").exists()
    assert not WarmupLog.objects.filter(action=action, level=WarmupLog.Level.INFO, message__contains="Виконується").exists()


@pytest.mark.django_db
def test_execute_warmup_action_keeps_running_plan_alive_with_next_random_action(monkeypatch):
    user = get_user_model().objects.create_user(email="warmup-loop@example.com", password="pass")
    account = TelegramAccount.objects.create(
        owner=user,
        label="Looper",
        session_name="looper",
        auth_state=TelegramAccount.AuthState.CONNECTED,
        status=TelegramAccount.Status.ACTIVE,
    )
    policy = WarmupPolicy.objects.create(
        owner=user,
        name="Loop",
        daily_join_min=1,
        daily_join_max=1,
        delay_min_seconds=60,
        delay_max_seconds=60,
        active_start_hour=0,
        active_end_hour=23,
        enable_view_dialogs=True,
        enable_channel_scroll=False,
        enable_mark_read=False,
        enable_typing_simulation=False,
        reaction_probability=0,
    )
    target = WarmupTarget.objects.create(owner=user, title="Target", value="@target_ua")
    plan = WarmupPlan.objects.create(owner=user, name="Plan", policy=policy, status=WarmupPlan.Status.RUNNING)
    plan.accounts.add(account)
    plan.targets.add(target)
    action = WarmupAction.objects.create(
        owner=user,
        plan=plan,
        account=account,
        target=target,
        action_type=WarmupAction.ActionType.READ,
        scheduled_for=timezone.now(),
    )
    monkeypatch.setattr("apps.warmup.services.run_client_operation", lambda account, operation: {"ok": True})
    monkeypatch.setattr("apps.warmup.services.schedule_action_dispatch", lambda action: None)

    action = execute_warmup_action(action.id)

    plan.refresh_from_db()
    assert action.status == WarmupAction.Status.SUCCEEDED
    assert plan.status == WarmupPlan.Status.RUNNING
    next_action = WarmupAction.objects.exclude(pk=action.pk).get(plan=plan)
    assert next_action.status == WarmupAction.Status.QUEUED
    assert next_action.metadata["cycle"] is True
    assert next_action.action_type == WarmupAction.ActionType.VIEW_DIALOGS


@pytest.mark.django_db
def test_folder_join_is_scheduled_immediately_before_gradual_channels(monkeypatch):
    monkeypatch.setattr("apps.warmup.services.schedule_action_dispatch", lambda action: None)
    user = get_user_model().objects.create_user(email="warmup-folder-order@example.com", password="pass")
    account = TelegramAccount.objects.create(
        owner=user,
        label="Folder Runner",
        session_name="folder-runner",
        auth_state=TelegramAccount.AuthState.CONNECTED,
        status=TelegramAccount.Status.ACTIVE,
    )
    policy = WarmupPolicy.objects.create(
        owner=user,
        name="Folder first",
        daily_join_min=2,
        daily_join_max=2,
        delay_min_seconds=600,
        delay_max_seconds=600,
        read_min_seconds=1,
        read_max_seconds=1,
        reaction_probability=0,
        active_start_hour=0,
        active_end_hour=23,
        allow_folder_one_click=True,
    )
    channel = WarmupTarget.objects.create(owner=user, title="Channel", value="@channel_one")
    folder = WarmupTarget.objects.create(
        owner=user,
        title="Folder",
        target_type=WarmupTarget.TargetType.FOLDER,
        value="https://t.me/addlist/abcdef",
    )
    plan = WarmupPlan.objects.create(owner=user, name="Plan", policy=policy)
    plan.accounts.add(account)
    plan.targets.add(channel, folder)

    from apps.warmup.services import start_warmup_plan

    before = timezone.now()
    start_warmup_plan(plan)

    folder_join = WarmupAction.objects.get(plan=plan, target=folder, action_type=WarmupAction.ActionType.JOIN_FOLDER)
    channel_join = WarmupAction.objects.get(plan=plan, target=channel, action_type=WarmupAction.ActionType.JOIN_CHANNEL)
    assert folder_join.scheduled_for <= before + timedelta(seconds=5)
    assert channel_join.scheduled_for >= before + timedelta(seconds=590)
    assert not WarmupLog.objects.filter(action=folder_join, message__contains="📁").exists()


def test_extract_addlist_slug_from_link():
    assert _extract_addlist_slug("https://t.me/addlist/A5vPDmECZ4yZjEy") == "A5vPDmECZ4yZjEy"
    assert _extract_addlist_slug("t.me/addlist/abc_123-XYZ") == "abc_123-XYZ"


def test_join_chatlist_invite_uses_raw_chatlist_api():
    target = WarmupTarget(title="Folder", target_type=WarmupTarget.TargetType.FOLDER, value="https://t.me/addlist/abc123")
    calls = []

    class FakeApp:
        async def invoke(self, request):
            calls.append(request)
            if isinstance(request, raw.functions.chatlists.CheckChatlistInvite):
                return SimpleNamespace(
                    title="Test folder",
                    peers=[raw.types.PeerChannel(channel_id=10)],
                    chats=[SimpleNamespace(id=10, title="Channel 10", access_hash=999)],
                    users=[],
                )
            return SimpleNamespace()

    result = asyncio.run(_join_chatlist_invite_operation(FakeApp(), target))

    assert isinstance(calls[0], raw.functions.chatlists.CheckChatlistInvite)
    assert isinstance(calls[1], raw.functions.chatlists.JoinChatlistInvite)
    assert calls[1].slug == "abc123"
    assert calls[1].peers[0].channel_id == 10
    assert result["joined_count"] == 1
    assert result["peer_titles"] == ["Channel 10"]


def test_view_dialogs_result_details_include_real_chat_titles():
    action = SimpleNamespace(
        action_type=WarmupAction.ActionType.VIEW_DIALOGS,
        target=SimpleNamespace(title="Folder", value="https://t.me/addlist/abc"),
    )

    details = _result_details(
        action,
        {
            "dialogs": 2,
            "chats": [
                {"title": "Crypto Drops UA", "type": "ChatType.CHANNEL", "unread_messages_count": 3},
                {"title": "Private Group", "type": "ChatType.SUPERGROUP", "unread_messages_count": 0},
            ],
        },
    )

    assert "Crypto Drops UA" in details
    assert "Private Group" in details
    assert "https://t.me/addlist" not in details


def test_folder_read_result_details_include_real_chat_titles():
    action = SimpleNamespace(
        action_type=WarmupAction.ActionType.READ,
        target=SimpleNamespace(title="Folder", value="https://t.me/addlist/abc"),
    )

    details = _result_details(
        action,
        {
            "messages": 7,
            "chats": [
                {"title": "News Channel", "messages": 5},
                {"title": "Group Chat", "messages": 2},
            ],
        },
    )

    assert "News Channel" in details
    assert "Group Chat" in details
    assert "7 пов." in details


def test_folder_passive_scan_uses_real_dialogs_not_addlist_link():
    target = WarmupTarget(title="Folder", target_type=WarmupTarget.TargetType.FOLDER, value="https://t.me/addlist/abc")

    class FakeApp:
        def __init__(self):
            self.history_refs = []

        async def get_dialogs(self, limit=5):
            dialogs = [
                SimpleNamespace(chat=SimpleNamespace(id=101, title="News Channel", username="news_channel")),
                SimpleNamespace(chat=SimpleNamespace(id=102, title="Group Chat", username="group_chat")),
            ]
            for dialog in dialogs[:limit]:
                yield dialog

        async def get_chat_history(self, chat_ref, limit=10):
            self.history_refs.append(chat_ref)
            yield SimpleNamespace(poll=True)
            yield SimpleNamespace(poll=None)

    app = FakeApp()
    result = asyncio.run(_passive_scan_operation(app, target, "poll"))

    assert result["seen"] == 4
    assert result["matched"] == 2
    assert app.history_refs == ["news_channel", "group_chat"]
    assert all("addlist" not in str(ref) for ref in app.history_refs)


def test_passive_scan_performs_action_on_specific_found_media():
    target = WarmupTarget(title="Folder", target_type=WarmupTarget.TargetType.FOLDER, value="https://t.me/addlist/abc")

    class FakeApp:
        def __init__(self):
            self.read_calls = []

        async def get_dialogs(self, limit=5):
            yield SimpleNamespace(chat=SimpleNamespace(id=101, title="Video Channel", username="video_channel"))

        async def get_chat_history(self, chat_ref, limit=20):
            yield SimpleNamespace(id=91, video=True)
            yield SimpleNamespace(id=90, video=None)

        async def read_chat_history(self, chat_ref, max_id=0):
            self.read_calls.append((chat_ref, max_id))
            return True

    app = FakeApp()
    result = asyncio.run(_passive_scan_operation(app, target, "video"))

    assert result["matched"] == 1
    assert result["performed_items"] == [
        {
            "chat": "Video Channel (@video_channel)",
            "message_id": 91,
            "media_type": "video",
            "action": "read_chat_history",
        }
    ]
    assert app.read_calls == [("video_channel", 91)]


def test_view_dialogs_samples_only_two_or_three_dialogs(monkeypatch):
    monkeypatch.setattr("apps.warmup.services.random.randint", lambda _min, _max: 3)

    class FakeApp:
        async def get_dialogs(self, limit=10):
            for index in range(10):
                if index >= limit:
                    break
                yield SimpleNamespace(
                    chat=SimpleNamespace(
                        id=index,
                        title=f"Dialog {index}",
                        username=f"dialog_{index}",
                        type="channel",
                    ),
                    unread_messages_count=index,
                    unread_mentions_count=0,
                )

    result = asyncio.run(_view_dialogs_operation(FakeApp()))

    assert result["dialogs"] == 3
    assert [chat["title"] for chat in result["chats"]] == [
        "Dialog 0 (@dialog_0)",
        "Dialog 1 (@dialog_1)",
        "Dialog 2 (@dialog_2)",
    ]


def test_passive_scan_limits_chat_fanout(monkeypatch):
    monkeypatch.setattr("apps.warmup.services.random.randint", lambda _min, _max: 3)
    target = WarmupTarget(title="Folder", target_type=WarmupTarget.TargetType.FOLDER, value="https://t.me/addlist/abc")

    class FakeApp:
        def __init__(self):
            self.history_refs = []

        async def get_dialogs(self, limit=30):
            for index in range(10):
                yield SimpleNamespace(chat=SimpleNamespace(id=index, title=f"Chat {index}", username=f"chat_{index}"))

        async def get_chat_history(self, chat_ref, limit=20):
            self.history_refs.append(chat_ref)
            yield SimpleNamespace(id=1, poll=None)

    app = FakeApp()
    result = asyncio.run(_passive_scan_operation(app, target, "poll", WarmupPolicy.WarmupSource.SUBSCRIPTIONS))

    assert len(result["chats"]) == 3
    assert len(app.history_refs) == 3
    assert result["seen"] == 3


def test_subscription_forward_uses_account_dialogs_not_join_target():
    target = WarmupTarget(title="Folder", target_type=WarmupTarget.TargetType.FOLDER, value="https://t.me/addlist/abc")

    class FakeApp:
        def __init__(self):
            self.forward_calls = []

        async def get_dialogs(self, limit=30):
            yield SimpleNamespace(chat=SimpleNamespace(id=201, title="Existing Channel", username="existing_channel"))

        async def get_chat_history(self, chat_ref, limit=1):
            yield SimpleNamespace(id=77)

        async def forward_messages(self, to_chat, from_chat, message_id):
            self.forward_calls.append((to_chat, from_chat, message_id))

    app = FakeApp()
    result = asyncio.run(_forward_message_operation(app, target, WarmupPolicy.WarmupSource.SUBSCRIPTIONS))

    assert result["forwarded"] is True
    assert result["chat"] == "Existing Channel (@existing_channel)"
    assert app.forward_calls == [("me", "existing_channel", 77)]


def test_forward_restricted_chat_falls_back_to_saved_message():
    target = WarmupTarget(title="Folder", target_type=WarmupTarget.TargetType.FOLDER, value="https://t.me/addlist/abc")

    class FakeApp:
        def __init__(self):
            self.saved_messages = []

        async def get_dialogs(self, limit=30):
            yield SimpleNamespace(chat=SimpleNamespace(id=201, title="Restricted Channel", username="restricted_channel"))

        async def get_chat_history(self, chat_ref, limit=1):
            yield SimpleNamespace(id=88, text="Important post text")

        async def forward_messages(self, to_chat, from_chat, message_id):
            raise RuntimeError('Telegram says: [400 CHAT_FORWARDS_RESTRICTED] - The chat restricts forwarding content')

        async def send_message(self, chat_id, text, **_kwargs):
            self.saved_messages.append((chat_id, text))
            return SimpleNamespace(id=501)

    app = FakeApp()
    result = asyncio.run(_forward_message_operation(app, target, WarmupPolicy.WarmupSource.SUBSCRIPTIONS))

    assert result["forwarded"] is False
    assert result["saved_fallback"] is True
    assert result["saved_message_id"] == 501
    assert result["chat"] == "Restricted Channel (@restricted_channel)"
    assert app.saved_messages[0][0] == "me"
    assert "message_id: 88" in app.saved_messages[0][1]


def test_forward_restricted_result_details_show_saved_fallback_location():
    action = SimpleNamespace(
        action_type=WarmupAction.ActionType.FORWARD_MESSAGE,
        target=SimpleNamespace(title="Folder", value="https://t.me/addlist/abc"),
        metadata={"warmup_source": WarmupPolicy.WarmupSource.SUBSCRIPTIONS},
    )

    details = _result_details(
        action,
        {
            "saved_fallback": True,
            "saved_message_id": 501,
            "message_id": 88,
            "chat": "Restricted Channel (@restricted_channel)",
            "preview": "Important post text",
        },
    )

    assert "Збережене" in details
    assert "Restricted Channel" in details
    assert "#88" in details


def test_next_active_time_supports_overnight_window():
    policy = WarmupPolicy(active_start_hour=23, active_end_hour=9)
    active_candidate = timezone.make_aware(datetime(2026, 4, 22, 23, 33, 0))
    inactive_candidate = timezone.make_aware(datetime(2026, 4, 22, 10, 15, 0))
    early_candidate = timezone.make_aware(datetime(2026, 4, 22, 3, 15, 0))

    assert next_active_time(policy, active_candidate) == active_candidate
    assert next_active_time(policy, early_candidate) == early_candidate
    adjusted = timezone.localtime(next_active_time(policy, inactive_candidate))
    assert adjusted.date() == timezone.localtime(inactive_candidate).date()
    assert adjusted.hour == 23


@pytest.mark.django_db
def test_overnight_warmup_schedule_does_not_push_each_action_to_next_day(monkeypatch):
    fixed_now = timezone.make_aware(datetime(2026, 4, 22, 23, 33, 0))
    monkeypatch.setattr("apps.warmup.services.timezone.now", lambda: fixed_now)
    monkeypatch.setattr("apps.warmup.services.schedule_action_dispatch", lambda action: None)
    user = get_user_model().objects.create_user(email="warmup-overnight@example.com", password="pass")
    account = TelegramAccount.objects.create(
        owner=user,
        label="Night Account",
        session_name="night-account",
        auth_state=TelegramAccount.AuthState.CONNECTED,
        status=TelegramAccount.Status.ACTIVE,
    )
    policy = WarmupPolicy.objects.create(
        owner=user,
        name="Night schedule",
        daily_join_min=1,
        daily_join_max=1,
        delay_min_seconds=60,
        delay_max_seconds=60,
        read_min_seconds=1,
        read_max_seconds=2,
        reaction_probability=0,
        active_start_hour=23,
        active_end_hour=9,
        enable_view_dialogs=True,
        enable_channel_scroll=True,
        enable_mark_read=True,
        enable_typing_simulation=False,
    )
    target = WarmupTarget.objects.create(owner=user, title="Target", value="@target_night")
    plan = WarmupPlan.objects.create(owner=user, name="Plan", policy=policy)
    plan.accounts.add(account)
    plan.targets.add(target)

    from apps.warmup.services import start_warmup_plan

    start_warmup_plan(plan)

    delays = list(WarmupAction.objects.filter(plan=plan).values_list("delay_seconds", flat=True))
    assert delays
    assert max(delays) < 3600


@pytest.mark.django_db
def test_initial_warmup_includes_reaction_and_spreads_over_session(monkeypatch):
    monkeypatch.setattr("apps.warmup.services.schedule_action_dispatch", lambda action: None)
    monkeypatch.setattr("apps.warmup.services.random.randint", lambda low, high: high)
    user = get_user_model().objects.create_user(email="warmup-session-spread@example.com", password="pass")
    account = TelegramAccount.objects.create(
        owner=user,
        label="Session Account",
        session_name="session-account",
        auth_state=TelegramAccount.AuthState.CONNECTED,
        status=TelegramAccount.Status.ACTIVE,
    )
    policy = WarmupPolicy.objects.create(
        owner=user,
        name="Spread",
        daily_join_min=1,
        daily_join_max=1,
        delay_min_seconds=60,
        delay_max_seconds=60,
        read_min_seconds=1,
        read_max_seconds=2,
        reaction_probability=1,
        max_reactions_per_day=1,
        session_duration_minutes=30,
        active_start_hour=0,
        active_end_hour=23,
        enable_reactions=True,
        enable_view_dialogs=True,
        enable_channel_scroll=True,
        enable_mark_read=True,
        enable_typing_simulation=True,
    )
    target = WarmupTarget.objects.create(owner=user, title="Target", value="@target_spread")
    plan = WarmupPlan.objects.create(owner=user, name="Plan", policy=policy)
    plan.accounts.add(account)
    plan.targets.add(target)

    from apps.warmup.services import start_warmup_plan

    start_warmup_plan(plan)

    actions = list(WarmupAction.objects.filter(plan=plan, metadata__initial_cycle=True).order_by("scheduled_for"))
    assert any(action.action_type == WarmupAction.ActionType.REACTION for action in actions)
    assert actions[-1].delay_seconds >= 20 * 60


@pytest.mark.django_db
def test_initial_cycle_success_does_not_create_extra_cycle_action(monkeypatch):
    user = get_user_model().objects.create_user(email="warmup-no-extra-cycle@example.com", password="pass")
    account = TelegramAccount.objects.create(
        owner=user,
        label="No Extra",
        session_name="no-extra",
        auth_state=TelegramAccount.AuthState.CONNECTED,
        status=TelegramAccount.Status.ACTIVE,
    )
    policy = WarmupPolicy.objects.create(owner=user, name="Safe")
    target = WarmupTarget.objects.create(owner=user, title="Target", value="@target_no_extra")
    plan = WarmupPlan.objects.create(owner=user, name="Plan", policy=policy, status=WarmupPlan.Status.RUNNING)
    plan.accounts.add(account)
    plan.targets.add(target)
    action = WarmupAction.objects.create(
        owner=user,
        plan=plan,
        account=account,
        target=target,
        action_type=WarmupAction.ActionType.VIEW_DIALOGS,
        scheduled_for=timezone.now(),
        metadata={"initial_cycle": True},
    )
    monkeypatch.setattr("apps.warmup.services.run_client_operation", lambda account, operation: {"dialogs": 1, "chats": []})
    monkeypatch.setattr("apps.warmup.services.schedule_action_dispatch", lambda action: None)

    execute_warmup_action(action.id)

    assert WarmupAction.objects.filter(plan=plan).count() == 1


@pytest.mark.django_db
def test_run_due_endpoint_processes_queued_actions(monkeypatch):
    user = get_user_model().objects.create_user(email="warmup-run-due@example.com", password="pass")
    account = TelegramAccount.objects.create(
        owner=user,
        label="Runner",
        session_name="runner-due",
        auth_state=TelegramAccount.AuthState.CONNECTED,
        status=TelegramAccount.Status.ACTIVE,
    )
    policy = WarmupPolicy.objects.create(owner=user, name="Safe", daily_join_min=1, daily_join_max=1)
    target = WarmupTarget.objects.create(owner=user, title="Target", value="@target_ua")
    plan = WarmupPlan.objects.create(owner=user, name="Plan", policy=policy, status=WarmupPlan.Status.RUNNING)
    plan.accounts.add(account)
    plan.targets.add(target)
    action = WarmupAction.objects.create(
        owner=user,
        plan=plan,
        account=account,
        target=target,
        action_type=WarmupAction.ActionType.JOIN_CHANNEL,
        scheduled_for=timezone.now() - timedelta(seconds=1),
    )
    monkeypatch.setattr("apps.warmup.services.run_client_operation", lambda account, operation: {"ok": True})
    client = Client()
    client.force_login(user)

    response = client.post(
        "/api/v1/warmup/actions/run-due/",
        data=json.dumps({"limit": 10}),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["processed"] == 1
    action.refresh_from_db()
    assert action.status == WarmupAction.Status.SUCCEEDED


@pytest.mark.django_db
def test_clear_warmup_actions_endpoint_deletes_only_owner_selected_status():
    user = get_user_model().objects.create_user(email="warmup-clear@example.com", password="pass")
    other_user = get_user_model().objects.create_user(email="warmup-clear-other@example.com", password="pass")
    account = TelegramAccount.objects.create(
        owner=user,
        label="Runner",
        session_name="runner-clear",
        auth_state=TelegramAccount.AuthState.CONNECTED,
        status=TelegramAccount.Status.ACTIVE,
    )
    other_account = TelegramAccount.objects.create(
        owner=other_user,
        label="Other",
        session_name="runner-clear-other",
        auth_state=TelegramAccount.AuthState.CONNECTED,
        status=TelegramAccount.Status.ACTIVE,
    )
    policy = WarmupPolicy.objects.create(owner=user, name="Safe", daily_join_min=1, daily_join_max=1)
    other_policy = WarmupPolicy.objects.create(owner=other_user, name="Other safe", daily_join_min=1, daily_join_max=1)
    target = WarmupTarget.objects.create(owner=user, title="Target", value="@target_ua")
    other_target = WarmupTarget.objects.create(owner=other_user, title="Other target", value="@other_target_ua")
    plan = WarmupPlan.objects.create(owner=user, name="Plan", policy=policy, status=WarmupPlan.Status.RUNNING)
    other_plan = WarmupPlan.objects.create(owner=other_user, name="Other Plan", policy=other_policy, status=WarmupPlan.Status.RUNNING)
    plan.accounts.add(account)
    plan.targets.add(target)
    other_plan.accounts.add(other_account)
    other_plan.targets.add(other_target)
    queued = WarmupAction.objects.create(
        owner=user,
        plan=plan,
        account=account,
        target=target,
        action_type=WarmupAction.ActionType.READ,
        scheduled_for=timezone.now(),
    )
    failed = WarmupAction.objects.create(
        owner=user,
        plan=plan,
        account=account,
        target=target,
        action_type=WarmupAction.ActionType.READ,
        status=WarmupAction.Status.FAILED,
        scheduled_for=timezone.now(),
    )
    other_queued = WarmupAction.objects.create(
        owner=other_user,
        plan=other_plan,
        account=other_account,
        target=other_target,
        action_type=WarmupAction.ActionType.READ,
        scheduled_for=timezone.now(),
    )
    client = Client()
    client.force_login(user)

    response = client.post(
        "/api/v1/warmup/actions/clear/",
        data=json.dumps({"mode": WarmupAction.Status.QUEUED, "purge_redis": False}),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["deleted"] == 1
    assert not WarmupAction.objects.filter(pk=queued.pk).exists()
    assert WarmupAction.objects.filter(pk=failed.pk).exists()
    assert WarmupAction.objects.filter(pk=other_queued.pk).exists()


@pytest.mark.django_db
def test_clear_warmup_actions_endpoint_can_delete_logs_and_revoke_tasks(monkeypatch):
    revoked = {}
    monkeypatch.setattr("apps.warmup.services._revoke_celery_tasks", lambda task_ids: revoked.setdefault("count", len(task_ids)))
    monkeypatch.setattr(
        "apps.warmup.services.purge_warmup_messages_from_redis",
        lambda: {"redis_scanned": 3, "redis_removed": 2, "redis_error": 0},
    )
    user = get_user_model().objects.create_user(email="warmup-clear-logs@example.com", password="pass")
    account = TelegramAccount.objects.create(
        owner=user,
        label="Runner",
        session_name="runner-clear-logs",
        auth_state=TelegramAccount.AuthState.CONNECTED,
        status=TelegramAccount.Status.ACTIVE,
    )
    policy = WarmupPolicy.objects.create(owner=user, name="Safe", daily_join_min=1, daily_join_max=1)
    target = WarmupTarget.objects.create(owner=user, title="Target", value="@target_logs")
    plan = WarmupPlan.objects.create(owner=user, name="Plan", policy=policy, status=WarmupPlan.Status.RUNNING)
    plan.accounts.add(account)
    plan.targets.add(target)
    action = WarmupAction.objects.create(
        owner=user,
        plan=plan,
        account=account,
        target=target,
        action_type=WarmupAction.ActionType.READ,
        celery_task_id="celery-task-1",
        scheduled_for=timezone.now(),
    )
    WarmupLog.objects.create(owner=user, plan=plan, action=action, account=account, message="old log")
    client = Client()
    client.force_login(user)

    response = client.post(
        "/api/v1/warmup/actions/clear/",
        data=json.dumps({"mode": "all", "clear_logs": True, "purge_redis": True}),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["deleted"] == 1
    assert response.json()["deleted_logs"] == 1
    assert response.json()["revoked"] == 1
    assert response.json()["redis_removed"] == 2
    assert not WarmupAction.objects.filter(pk=action.pk).exists()
    assert not WarmupLog.objects.filter(owner=user).exists()


@pytest.mark.django_db
def test_stop_warmup_plan_endpoint_deletes_plan_actions_and_revokes_tasks(monkeypatch):
    revoked = {}
    monkeypatch.setattr("apps.warmup.services._revoke_celery_tasks", lambda task_ids: revoked.setdefault("count", len(task_ids)))
    monkeypatch.setattr(
        "apps.warmup.services.purge_warmup_messages_from_redis",
        lambda: {"redis_scanned": 2, "redis_removed": 1, "redis_error": 0},
    )
    user = get_user_model().objects.create_user(email="warmup-stop@example.com", password="pass")
    account = TelegramAccount.objects.create(
        owner=user,
        label="Stopper",
        session_name="stopper",
        auth_state=TelegramAccount.AuthState.CONNECTED,
        status=TelegramAccount.Status.ACTIVE,
    )
    policy = WarmupPolicy.objects.create(owner=user, name="Safe", daily_join_min=1, daily_join_max=1)
    target = WarmupTarget.objects.create(owner=user, title="Target", value="@target_stop")
    plan = WarmupPlan.objects.create(owner=user, name="Plan", policy=policy, status=WarmupPlan.Status.RUNNING)
    plan.accounts.add(account)
    plan.targets.add(target)
    action = WarmupAction.objects.create(
        owner=user,
        plan=plan,
        account=account,
        target=target,
        action_type=WarmupAction.ActionType.READ,
        celery_task_id="celery-task-stop",
        scheduled_for=timezone.now(),
    )
    WarmupLog.objects.create(owner=user, plan=plan, action=action, account=account, message="old log")
    client = Client()
    client.force_login(user)

    response = client.post(
        f"/api/v1/warmup/plans/{plan.id}/stop/",
        data=json.dumps({"purge_redis": True}),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["deleted_actions"] == 1
    assert response.json()["deleted_logs"] == 1
    assert response.json()["revoked"] == 1
    assert response.json()["redis_removed"] == 1
    assert not WarmupPlan.objects.filter(pk=plan.pk).exists()
    assert not WarmupAction.objects.filter(pk=action.pk).exists()
    assert not WarmupLog.objects.filter(owner=user).exists()


@pytest.mark.django_db
def test_clear_warmup_actions_endpoint_rejects_invalid_mode():
    user = get_user_model().objects.create_user(email="warmup-clear-invalid@example.com", password="pass")
    client = Client()
    client.force_login(user)

    response = client.post(
        "/api/v1/warmup/actions/clear/",
        data=json.dumps({"mode": "drop_table", "purge_redis": False}),
        content_type="application/json",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_execute_warmup_action_task_ignores_deleted_action():
    result = execute_warmup_action_task(999999)

    assert result == {"action_id": 999999, "status": "deleted"}


@pytest.mark.django_db
def test_execute_warmup_action_task_ignores_action_deleted_during_execution(monkeypatch):
    def raise_deleted(_action_id):
        raise WarmupAction.DoesNotExist()

    monkeypatch.setattr("apps.warmup.tasks.execute_warmup_action", raise_deleted)

    result = execute_warmup_action_task(123)

    assert result == {"action_id": 123, "status": "deleted"}


@pytest.mark.django_db
def test_register_account_runtime_event_task_ignores_deleted_account():
    result = register_account_runtime_event_task(999999, AccountHealthEvent.EventType.SUCCESS, {"source": "test"})

    assert result == {"account_id": 999999, "event_type": AccountHealthEvent.EventType.SUCCESS, "status": "deleted"}
