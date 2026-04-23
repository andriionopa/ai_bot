from __future__ import annotations

import asyncio
import json
import random
import re
from datetime import timedelta

import redis
from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from pyrogram import raw

from apps.realtime.logging import publish_log_event
from apps.telegram_accounts.models import AccountHealthEvent, TelegramAccount
from apps.telegram_accounts.services import (
    get_account_runtime_block_reason,
    register_account_runtime_event,
    run_client_operation,
)
from apps.warmup.models import WarmupAction, WarmupLog, WarmupPlan, WarmupPolicy, WarmupTarget
from workers.telegram_runtime.guard import classify_runtime_exception


REACTIONS = ("👍", "🔥", "👏", "👌", "❤️")
WARMUP_TASK_NAMES = {
    "apps.warmup.tasks.execute_warmup_action_task",
    "apps.warmup.tasks.process_due_warmup_actions_task",
}
PASSIVE_SCAN_ACTIONS = {
    WarmupAction.ActionType.POLL_SCAN: "poll",
    WarmupAction.ActionType.VIDEO_SCAN: "video",
    WarmupAction.ActionType.VOICE_SCAN: "voice",
    WarmupAction.ActionType.STICKER_SCAN: "sticker",
    WarmupAction.ActionType.LINK_PREVIEW: "link",
    WarmupAction.ActionType.EMOJI_STATUS_CHECK: "emoji_status",
    WarmupAction.ActionType.DRAFTS_CHECK: "drafts",
    WarmupAction.ActionType.NOTIFICATION_CHECK: "notifications",
    WarmupAction.ActionType.ARCHIVE_CHECK: "archive",
    WarmupAction.ActionType.MUTE_CHECK: "mute",
}
SCENARIO_FLAGS: tuple[tuple[str, str], ...] = (
    ("enable_account_dialogs", WarmupAction.ActionType.ACCOUNT_DIALOG),
    ("enable_story_view", WarmupAction.ActionType.STORY_VIEW),
    ("enable_trust_boost", WarmupAction.ActionType.TRUST_BOOST),
    ("enable_view_dialogs", WarmupAction.ActionType.VIEW_DIALOGS),
    ("enable_channel_scroll", WarmupAction.ActionType.CHANNEL_SCROLL),
    ("enable_mark_read", WarmupAction.ActionType.MARK_READ),
    ("enable_message_search", WarmupAction.ActionType.MESSAGE_SEARCH),
    ("enable_forward_messages", WarmupAction.ActionType.FORWARD_MESSAGE),
    ("enable_saved_notes", WarmupAction.ActionType.SAVED_NOTE),
    ("enable_poll_scan", WarmupAction.ActionType.POLL_SCAN),
    ("enable_video_scan", WarmupAction.ActionType.VIDEO_SCAN),
    ("enable_voice_scan", WarmupAction.ActionType.VOICE_SCAN),
    ("enable_gif_search", WarmupAction.ActionType.GIF_SEARCH),
    ("enable_sticker_scan", WarmupAction.ActionType.STICKER_SCAN),
    ("enable_inline_bot_check", WarmupAction.ActionType.INLINE_BOT_CHECK),
    ("enable_link_preview", WarmupAction.ActionType.LINK_PREVIEW),
    ("enable_typing_simulation", WarmupAction.ActionType.TYPING_SIMULATION),
    ("enable_profile_view", WarmupAction.ActionType.PROFILE_VIEW),
    ("enable_settings_check", WarmupAction.ActionType.SETTINGS_CHECK),
    ("enable_gradual_profile_check", WarmupAction.ActionType.GRADUAL_PROFILE_CHECK),
    ("enable_emoji_status_check", WarmupAction.ActionType.EMOJI_STATUS_CHECK),
    ("enable_drafts_check", WarmupAction.ActionType.DRAFTS_CHECK),
    ("enable_notification_check", WarmupAction.ActionType.NOTIFICATION_CHECK),
    ("enable_scheduled_message_check", WarmupAction.ActionType.SCHEDULED_MESSAGE_CHECK),
    ("enable_archive_check", WarmupAction.ActionType.ARCHIVE_CHECK),
    ("enable_mute_check", WarmupAction.ActionType.MUTE_CHECK),
)
JOIN_ACTION_TYPES = {
    WarmupAction.ActionType.JOIN_CHANNEL,
    WarmupAction.ActionType.JOIN_FOLDER,
}
NON_JOIN_ACTION_TYPES = tuple(action_type for _flag, action_type in SCENARIO_FLAGS)
MESSAGE_SENDING_ACTION_TYPES = {
    WarmupAction.ActionType.ACCOUNT_DIALOG,
    WarmupAction.ActionType.FORWARD_MESSAGE,
    WarmupAction.ActionType.SAVED_NOTE,
    WarmupAction.ActionType.SCHEDULED_MESSAGE_CHECK,
}
WARMUP_CHAT_SAMPLE_MIN = 2
WARMUP_CHAT_SAMPLE_MAX = 3
PASSIVE_SCAN_CHAT_LIMIT = 3
PASSIVE_SCAN_HISTORY_LIMIT = 20
PASSIVE_SCAN_PERFORM_LIMIT = 5
BEHAVIOR_CAPS = {
    WarmupPolicy.BehaviorProfile.SAFE: {"daily_max": 15, "reaction_probability": 25, "actions_per_hour": 8, "actions_per_day": 60},
    WarmupPolicy.BehaviorProfile.BALANCED: {"daily_max": 30, "reaction_probability": 45, "actions_per_hour": 15, "actions_per_day": 100},
    WarmupPolicy.BehaviorProfile.AGGRESSIVE: {"daily_max": 50, "reaction_probability": 65, "actions_per_hour": 30, "actions_per_day": 180},
}
ACTION_LABELS = {
    WarmupAction.ActionType.JOIN_CHANNEL: ("🚪", "вступ у канал/групу"),
    WarmupAction.ActionType.JOIN_FOLDER: ("📁", "вступ через папку addlist"),
    WarmupAction.ActionType.VIEW_DIALOGS: ("👀", "перегляд діалогів"),
    WarmupAction.ActionType.CHANNEL_SCROLL: ("📜", "прокрутка каналу"),
    WarmupAction.ActionType.READ: ("📖", "читання постів"),
    WarmupAction.ActionType.ACCOUNT_DIALOG: ("💬", "діалоги між акаунтами"),
    WarmupAction.ActionType.STORY_VIEW: ("🎞️", "перегляд сторіс"),
    WarmupAction.ActionType.TRUST_BOOST: ("⭐", "підвищення довіри"),
    WarmupAction.ActionType.MARK_READ: ("✅", "позначення як прочитано"),
    WarmupAction.ActionType.MESSAGE_SEARCH: ("🔎", "пошук повідомлень"),
    WarmupAction.ActionType.REACTION: ("💬", "реакція на пост"),
    WarmupAction.ActionType.FORWARD_MESSAGE: ("↗️", "пересилка в збережене"),
    WarmupAction.ActionType.SAVED_NOTE: ("📝", "нотатка в збережене"),
    WarmupAction.ActionType.POLL_SCAN: ("📊", "перевірка опитувань"),
    WarmupAction.ActionType.VIDEO_SCAN: ("🎬", "перегляд відео"),
    WarmupAction.ActionType.VOICE_SCAN: ("🎧", "прослуховування voice"),
    WarmupAction.ActionType.GIF_SEARCH: ("🖼️", "пошук GIF"),
    WarmupAction.ActionType.STICKER_SCAN: ("🏷️", "перегляд стікерів"),
    WarmupAction.ActionType.INLINE_BOT_CHECK: ("🤖", "перевірка inline-бота"),
    WarmupAction.ActionType.LINK_PREVIEW: ("🔗", "preview посилань"),
    WarmupAction.ActionType.TYPING_SIMULATION: ("⌨️", "симуляція набору"),
    WarmupAction.ActionType.PROFILE_VIEW: ("👤", "перегляд профілю/каналу"),
    WarmupAction.ActionType.SETTINGS_CHECK: ("⚙️", "перевірка налаштувань"),
    WarmupAction.ActionType.GRADUAL_PROFILE_CHECK: ("🪪", "перевірка профілю"),
    WarmupAction.ActionType.EMOJI_STATUS_CHECK: ("🙂", "перевірка emoji-status"),
    WarmupAction.ActionType.DRAFTS_CHECK: ("📄", "перевірка чернеток"),
    WarmupAction.ActionType.NOTIFICATION_CHECK: ("🔔", "перевірка сповіщень"),
    WarmupAction.ActionType.SCHEDULED_MESSAGE_CHECK: ("⏰", "відкладене повідомлення"),
    WarmupAction.ActionType.ARCHIVE_CHECK: ("🗄️", "перевірка архіву"),
    WarmupAction.ActionType.MUTE_CHECK: ("🔕", "перевірка mute"),
}


def _action_label(action_type: str) -> tuple[str, str]:
    return ACTION_LABELS.get(action_type, ("ℹ️", action_type))


def _target_label(target: WarmupTarget | None) -> str:
    if target is None:
        return "без target"
    return f"{target.title} ({target.value})"


def _action_warmup_source(action: WarmupAction) -> str:
    metadata_source = action.metadata.get("warmup_source")
    if metadata_source:
        return metadata_source
    policy = getattr(getattr(action, "plan", None), "policy", None)
    return getattr(policy, "warmup_source", WarmupPolicy.WarmupSource.TARGETS)


def _action_place_label(action: WarmupAction) -> str:
    if action.action_type in JOIN_ACTION_TYPES:
        return _target_label(action.target)
    if action.action_type in {
        WarmupAction.ActionType.SAVED_NOTE,
        WarmupAction.ActionType.SCHEDULED_MESSAGE_CHECK,
    }:
        return "Збережене"
    if _action_warmup_source(action) == WarmupPolicy.WarmupSource.SUBSCRIPTIONS:
        return "підписках акаунта"
    return _target_label(action.target)


def _collect_result_places(action: WarmupAction, result: dict[str, object]) -> list[str]:
    places: list[str] = []

    def _push(value):
        if not value:
            return
        text = str(value).strip()
        if text and text not in places:
            places.append(text)

    if action.action_type == WarmupAction.ActionType.JOIN_FOLDER:
        for name in result.get("peer_titles", [])[:8]:
            _push(name)
        if places:
            return places

    if action.action_type == WarmupAction.ActionType.JOIN_CHANNEL:
        _push(result.get("title") or result.get("username") or result.get("id"))
        if places:
            return places

    _push(result.get("chat"))
    _push(result.get("profile_checked"))
    _push(result.get("target"))
    _push(result.get("story_owner"))

    chats = result.get("chats")
    if isinstance(chats, list):
        for item in chats[:3]:
            if isinstance(item, dict):
                _push(item.get("title"))
            else:
                _push(item)

    for title in (result.get("dialog_titles") or [])[:8]:
        _push(title)

    if action.action_type in {
        WarmupAction.ActionType.SAVED_NOTE,
        WarmupAction.ActionType.SCHEDULED_MESSAGE_CHECK,
        WarmupAction.ActionType.FORWARD_MESSAGE,
    }:
        _push("Збережене")
    if action.action_type in {
        WarmupAction.ActionType.SETTINGS_CHECK,
        WarmupAction.ActionType.GRADUAL_PROFILE_CHECK,
    }:
        _push("Власний профіль")

    return places


def _result_place_label(action: WarmupAction, result: dict[str, object]) -> str:
    places = _collect_result_places(action, result)
    if not places:
        return _action_place_label(action)
    if len(places) == 1:
        return places[0]
    return ", ".join(places[:3])


def _shorten_text(value: object, limit: int = 220) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)].rstrip()}…"


def _brief_titles(items, *, key: str | None = None, limit: int = 2) -> str:
    titles = []
    for item in items[:limit]:
        if isinstance(item, dict):
            value = item.get(key or "title")
        else:
            value = item
        if value:
            titles.append(str(value))
    extra = max(0, len(items) - len(titles))
    suffix = f" + ще {extra}" if extra else ""
    return ", ".join(titles) + suffix if titles else ""


def _format_delay(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} с"
    minutes, rest = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} хв {rest} с"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} год {minutes} хв"


def _action_context(action: WarmupAction) -> dict[str, object]:
    emoji, label = _action_label(action.action_type)
    return {
        "emoji": emoji,
        "action_label": label,
        "action_type": action.action_type,
        "account_label": action.account.label,
        "target_title": action.target.title,
        "target_value": action.target.value,
        "target_type": action.target.target_type,
        "visibility": action.target.visibility,
        "plan_name": action.plan.name,
    }


def _queued_message(action: WarmupAction) -> str:
    emoji, label = _action_label(action.action_type)
    scheduled_at = timezone.localtime(action.scheduled_for).strftime("%H:%M:%S")
    return (
        f"{emoji} Заплановано: {action.account.label} → {label} "
        f"у «{_action_place_label(action)}» о {scheduled_at} "
        f"(затримка {_format_delay(action.delay_seconds)})"
    )


def _queued_cycle_message(action: WarmupAction) -> str:
    emoji, label = _action_label(action.action_type)
    scheduled_at = timezone.localtime(action.scheduled_for).strftime("%H:%M:%S")
    return (
        f"🔁 Заплановано (наступний цикл): {action.account.label} → {label} "
        f"у «{_action_place_label(action)}» о {scheduled_at} "
        f"(затримка {_format_delay(action.delay_seconds)})"
    )


def _started_message(action: WarmupAction) -> str:
    emoji, label = _action_label(action.action_type)
    details = []
    if action.action_type == WarmupAction.ActionType.REACTION:
        details.append(f"реакція {action.metadata.get('reaction') or '👍'}")
    if action.action_type in {WarmupAction.ActionType.MESSAGE_SEARCH, WarmupAction.ActionType.GIF_SEARCH}:
        details.append(f"запит «{action.metadata.get('query') or 'crypto'}»")
    if action.action_type == WarmupAction.ActionType.INLINE_BOT_CHECK:
        details.append(f"бот @{action.metadata.get('bot') or 'gif'}, запит «{action.metadata.get('query') or 'cat'}»")
    suffix = f" | {'; '.join(details)}" if details else ""
    return f"{emoji} Виконується: {action.account.label} зараз робить «{label}» у «{_action_place_label(action)}»{suffix}"


def _result_details(action: WarmupAction, result: dict[str, object]) -> str:
    if action.action_type in {WarmupAction.ActionType.JOIN_CHANNEL, WarmupAction.ActionType.JOIN_FOLDER}:
        if action.action_type == WarmupAction.ActionType.JOIN_FOLDER:
            joined = result.get("joined_count", 0)
            joined_confirmed = result.get("joined_confirmed_count")
            already = result.get("already_count", 0)
            skipped = result.get("skipped_count", 0)
            names = ", ".join(result.get("peer_titles", [])[:5])
            suffix = f": {names}" if names else ""
            if result.get("already") and not joined:
                return f"папка «{result.get('folder_title') or action.target.title}» вже додана, нових чатів немає"
            confirmed_suffix = ""
            if joined_confirmed is not None:
                confirmed_suffix = f", підтверджено у діалогах {joined_confirmed}"
            skipped_suffix = f", пропущено {skipped}" if skipped else ""
            return (
                f"додав з папки «{result.get('folder_title') or action.target.title}» "
                f"{joined} чатів/каналів{confirmed_suffix}{skipped_suffix}, вже було {already}{suffix}"
            )
        title = result.get("title") or result.get("username") or result.get("id") or action.target.title
        return f"приєднався/відкрив target «{title}»"
    if action.action_type == WarmupAction.ActionType.READ:
        chats = result.get("chats") or []
        if chats:
            return f"прочитав {result.get('messages', 0)} пов. у {len(chats)} чатах: {_brief_titles(chats)}"
        return f"прочитав {result.get('messages', 0)} повідомлень"
    if action.action_type == WarmupAction.ActionType.REACTION:
        reaction = result.get("reaction") or action.metadata.get("reaction") or "👍"
        message_id = result.get("message_id") or "не знайдено"
        chat = result.get("chat")
        suffix = f" у чаті «{chat}»" if chat else ""
        return f"поставив реакцію {reaction} на пост #{message_id}{suffix}"
    if action.action_type == WarmupAction.ActionType.CHANNEL_SCROLL:
        chats = result.get("chats") or []
        if chats:
            return f"прокрутив {result.get('scrolled_messages', 0)} пов. у {len(chats)} чатах: {_brief_titles(chats)}"
        return f"прокрутив {result.get('scrolled_messages', 0)} повідомлень"
    if action.action_type == WarmupAction.ActionType.MARK_READ:
        chats = result.get("chats") or []
        return f"позначив прочитаним {len(chats)} чат(и): {_brief_titles(chats)}" if chats else "позначив історію як прочитану"
    if action.action_type == WarmupAction.ActionType.VIEW_DIALOGS:
        chats = result.get("chats") or []
        if chats:
            names = ", ".join(f"{chat.get('title')} unread={chat.get('unread_messages_count', 0)}" for chat in chats[:2])
            suffix = f" + ще {len(chats) - 2}" if len(chats) > 2 else ""
            return f"переглянув {result.get('dialogs', 0)} діалоги: {names}{suffix}"
        return f"переглянув {result.get('dialogs', 0)} діалогів"
    if action.action_type == WarmupAction.ActionType.ACCOUNT_DIALOG:
        if result.get("sent"):
            return (
                f"створив діалог між акаунтами: надіслав «{result.get('text')}» "
                f"до «{result.get('peer')}»"
            )
        peers = result.get("peers") or []
        if peers:
            return f"перевірив можливі діалоги між акаунтами: {', '.join(peers[:8])}"
        reason = result.get("reason") or "потрібно 2+ акаунти у плані"
        return f"діалоги між акаунтами не запускались: {reason}"
    if action.action_type == WarmupAction.ActionType.STORY_VIEW:
        owner = result.get("story_owner") or result.get("title") or action.target.title
        story_items = result.get("story_items") or []
        items_suffix = ""
        if story_items:
            items_suffix = "; " + ", ".join(
                f"{item.get('title')} max_id={item.get('max_id') or '-'}"
                for item in story_items[:5]
            )
        return f"перевірив сторіс у «{owner}», доступних сторіс {result.get('stories', 0)}{items_suffix}"
    if action.action_type == WarmupAction.ActionType.TRUST_BOOST:
        signals = ", ".join(result.get("signals", []) or [])
        dialogs = result.get("dialog_titles") or []
        dialogs_suffix = f"; діалоги: {', '.join(dialogs[:5])}" if dialogs else ""
        profile = result.get("profile_checked")
        profile_suffix = f"; профіль: «{profile}»" if profile else ""
        return f"зробив trust-сценарій: {signals or 'profile, read, dialogs'}{profile_suffix}{dialogs_suffix}"
    if action.action_type == WarmupAction.ActionType.MESSAGE_SEARCH:
        chats = result.get("chats") or []
        if chats:
            return f"пошук «{result.get('query')}»: {result.get('matches', 0)} збігів у {len(chats)} чатах"
        return f"пошук «{result.get('query')}»: знайдено {result.get('matches', 0)}"
    if action.action_type == WarmupAction.ActionType.FORWARD_MESSAGE:
        if result.get("saved_fallback"):
            chat = result.get("chat")
            suffix = f" з чату «{chat}»" if chat else ""
            preview = result.get("preview")
            preview_suffix = f"; текст: «{preview}»" if preview else ""
            return (
                f"чат забороняє forward, тому зберіг fallback у «Збережене» "
                f"#{result.get('saved_message_id')} для поста #{result.get('message_id')}{suffix}{preview_suffix}"
            )
        if result.get("forwarded"):
            chat = result.get("chat")
            suffix = f" з чату «{chat}»" if chat else ""
            preview = result.get("preview")
            preview_suffix = f"; текст: «{preview}»" if preview else ""
            return f"переслав пост #{result.get('message_id')}{suffix}{preview_suffix}"
        return "нічого не переслав: історія порожня"
    if action.action_type == WarmupAction.ActionType.SAVED_NOTE:
        return f"створив нотатку #{result.get('saved_message_id')}"
    if action.action_type in PASSIVE_SCAN_ACTIONS:
        chats = result.get("chats") or []
        matched_items = result.get("matched_items") or []
        performed_items = result.get("performed_items") or []
        items_suffix = ""
        if performed_items:
            rendered = ", ".join(
                f"{item.get('chat')}#{item.get('message_id')} ({item.get('media_type')})"
                for item in performed_items[:2]
            )
            items_suffix = f"; виконано: {rendered}"
        elif matched_items:
            rendered = ", ".join(
                f"{item.get('chat')}#{item.get('message_id')}"
                for item in matched_items[:2]
            )
            items_suffix = f"; приклади: {rendered}"
        if chats:
            action_word = "знайшов і відкрив" if performed_items else "перевірив"
            return (
                f"{action_word}: {len(chats)} чат(и), {result.get('seen', 0)} пов., "
                f"{result.get('matched', 0)} збігів{items_suffix}"
            )
        return f"перевірив {result.get('seen', 0)} повідомлень, збігів {result.get('matched', 0)}"
    if action.action_type in {WarmupAction.ActionType.INLINE_BOT_CHECK, WarmupAction.ActionType.GIF_SEARCH}:
        first_id = result.get("first_result_id")
        first_type = result.get("first_result_type")
        first_suffix = f"; first_result id={first_id}, type={first_type or '-'}" if first_id else ""
        return (
            f"inline @{result.get('bot')}: результатів {result.get('results', 0)} "
            f"за запитом «{result.get('query')}»{first_suffix}"
        )
    if action.action_type == WarmupAction.ActionType.TYPING_SIMULATION:
        chat = result.get("chat")
        if chat:
            return f"показав статус набору повідомлення у чаті «{chat}»"
        return "показав статус набору повідомлення"
    if action.action_type == WarmupAction.ActionType.PROFILE_VIEW:
        return f"переглянув профіль/чат «{result.get('title') or result.get('chat_id')}»"
    if action.action_type in {WarmupAction.ActionType.SETTINGS_CHECK, WarmupAction.ActionType.GRADUAL_PROFILE_CHECK}:
        return f"перевірив власний профіль user_id={result.get('user_id')}, username={result.get('username') or '-'}"
    if action.action_type == WarmupAction.ActionType.SCHEDULED_MESSAGE_CHECK:
        chat = result.get("chat") or "Збережене"
        text = result.get("text") or ""
        scheduled_for = result.get("scheduled_for") or ""
        text_suffix = f"; текст: «{text}»" if text else ""
        date_suffix = f"; дата: {scheduled_for}" if scheduled_for else ""
        return f"створив відкладене повідомлення #{result.get('scheduled_message_id')} у «{chat}»{text_suffix}{date_suffix}"
    return ", ".join(f"{key}={value}" for key, value in result.items()) or "дію виконано"


def _success_message(action: WarmupAction, result: dict[str, object]) -> str:
    emoji, label = _action_label(action.action_type)
    message = f"✅ {emoji} Готово: {action.account.label} виконав «{label}» у «{_result_place_label(action, result)}» — {_result_details(action, result)}"
    return _shorten_text(message, 260)


def _failed_message(action: WarmupAction, error: str) -> str:
    emoji, label = _action_label(action.action_type)
    return f"❌ {emoji} Помилка: {action.account.label} не виконав «{label}» у «{_action_place_label(action)}» — {error}"


def _skipped_message(action: WarmupAction, reason: str) -> str:
    emoji, label = _action_label(action.action_type)
    return f"⚠️ {emoji} Пропущено: {action.account.label} не робить «{label}» у «{_action_place_label(action)}» — {reason}"


def log_warmup_event(
    *,
    owner,
    level: str,
    message: str,
    plan: WarmupPlan | None = None,
    action: WarmupAction | None = None,
    account: TelegramAccount | None = None,
    metadata: dict[str, object] | None = None,
) -> WarmupLog:
    log = WarmupLog.objects.create(
        owner=owner,
        level=level,
        message=message[:500],
        plan=plan,
        action=action,
        account=account,
        metadata=metadata or {},
    )
    publish_log_event(
        {
            "level": "info" if level == WarmupLog.Level.SUCCESS else level,
            "source": "warmup",
            "message": message,
            "plan_id": plan.id if plan else None,
            "action_id": action.id if action else None,
            "account_id": account.id if account else None,
            **(metadata or {}),
        }
    )
    return log


def _progressive_ramp_factor(policy: WarmupPolicy, now=None) -> float:
    if not policy.progressive_ramp:
        return 1.0
    now = now or timezone.now()
    policy_day = max(1, (timezone.localdate(now) - timezone.localdate(policy.created_at or now)).days + 1)
    ramp_day = min(policy_day, 7)
    return 0.3 + ((ramp_day - 1) * 0.7 / 6)


def _scale_limit(value: int, factor: float, *, minimum: int = 1) -> int:
    return max(minimum, int(round(value * factor)))


def clamp_policy(policy: WarmupPolicy) -> dict[str, int]:
    caps = BEHAVIOR_CAPS.get(policy.behavior_profile, BEHAVIOR_CAPS[WarmupPolicy.BehaviorProfile.BALANCED])
    factor = _progressive_ramp_factor(policy)
    daily_join_min = max(1, min(policy.daily_join_min, caps["daily_max"]))
    daily_join_max = max(1, min(policy.daily_join_max, caps["daily_max"]))
    reaction_probability = min(policy.reaction_probability, caps["reaction_probability"])
    max_reactions_per_day = min(policy.max_reactions_per_day, caps["daily_max"])
    actions_per_hour = min(policy.actions_per_hour, caps["actions_per_hour"]) if policy.auto_adapt_limits else policy.actions_per_hour
    actions_per_day = min(policy.actions_per_day, caps["actions_per_day"]) if policy.auto_adapt_limits else policy.actions_per_day
    scaled_daily_min = _scale_limit(daily_join_min, factor)
    scaled_daily_max = _scale_limit(daily_join_max, factor)
    return {
        "daily_join_min": min(scaled_daily_min, scaled_daily_max),
        "daily_join_max": max(scaled_daily_min, scaled_daily_max),
        "reaction_probability": _scale_limit(reaction_probability, factor, minimum=0),
        "max_reactions_per_day": _scale_limit(max_reactions_per_day, factor),
        "actions_per_hour": _scale_limit(actions_per_hour, factor),
        "actions_per_day": _scale_limit(actions_per_day, factor),
    }


def _next_day_active_time(policy: WarmupPolicy, now):
    tomorrow = timezone.localtime(now) + timedelta(days=1)
    candidate = tomorrow.replace(hour=policy.active_start_hour, minute=random.randint(0, 45), second=0, microsecond=0)
    return candidate.astimezone(timezone.get_current_timezone())


def _account_actions_today(account: TelegramAccount, now) -> int:
    day_start = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.get_current_timezone())
    return WarmupAction.objects.filter(
        account=account,
        status__in=[WarmupAction.Status.SUCCEEDED, WarmupAction.Status.QUEUED, WarmupAction.Status.RUNNING],
        scheduled_for__gte=day_start,
    ).count()


def _account_actions_this_hour(account: TelegramAccount, now) -> int:
    hour_start = timezone.localtime(now).replace(minute=0, second=0, microsecond=0).astimezone(timezone.get_current_timezone())
    return WarmupAction.objects.filter(
        account=account,
        status__in=[WarmupAction.Status.SUCCEEDED, WarmupAction.Status.QUEUED, WarmupAction.Status.RUNNING],
        scheduled_for__gte=hour_start,
    ).count()


def _is_within_active_window(policy: WarmupPolicy, local_candidate) -> bool:
    start_hour = policy.active_start_hour
    end_hour = policy.active_end_hour
    if start_hour == end_hour:
        return True
    if start_hour < end_hour:
        return start_hour <= local_candidate.hour <= end_hour
    return local_candidate.hour >= start_hour or local_candidate.hour <= end_hour


def next_active_time(policy: WarmupPolicy, candidate):
    local_candidate = timezone.localtime(candidate)
    start_hour = policy.active_start_hour
    if _is_within_active_window(policy, local_candidate):
        return candidate

    if start_hour < policy.active_end_hour and local_candidate.hour < start_hour:
        adjusted = local_candidate.replace(hour=start_hour, minute=random.randint(0, 45), second=0, microsecond=0)
    elif start_hour > policy.active_end_hour and local_candidate.hour < start_hour and local_candidate.hour > policy.active_end_hour:
        adjusted = local_candidate.replace(hour=start_hour, minute=random.randint(0, 45), second=0, microsecond=0)
    else:
        tomorrow = local_candidate + timedelta(days=1)
        adjusted = tomorrow.replace(hour=start_hour, minute=random.randint(0, 45), second=0, microsecond=0)
    return adjusted.astimezone(timezone.get_current_timezone())


def plan_queryset_with_counts(queryset):
    return queryset.annotate(
        account_count=Count("accounts", distinct=True),
        target_count=Count("targets", distinct=True),
        queued_count=Count("actions", filter=Q(actions__status=WarmupAction.Status.QUEUED), distinct=True),
        succeeded_count=Count("actions", filter=Q(actions__status=WarmupAction.Status.SUCCEEDED), distinct=True),
        failed_count=Count("actions", filter=Q(actions__status=WarmupAction.Status.FAILED), distinct=True),
        skipped_count=Count("actions", filter=Q(actions__status=WarmupAction.Status.SKIPPED), distinct=True),
    )


def schedule_action_dispatch(action: WarmupAction) -> None:
    try:
        from apps.warmup.tasks import execute_warmup_action_task

        result = execute_warmup_action_task.apply_async(args=[action.id], eta=action.scheduled_for)
        WarmupAction.objects.filter(pk=action.pk).update(celery_task_id=result.id)
        action.celery_task_id = result.id
    except Exception as exc:
        log_warmup_event(
            owner=action.owner,
            level=WarmupLog.Level.WARNING,
            plan=action.plan,
            action=action,
            account=action.account,
            message=(
                "⚠️ Черга Celery недоступна: дію залишено в queued. "
                "Перевірте worker/broker або виконайте run-due вручну."
            ),
            metadata={
                **_action_context(action),
                "queue_dispatch_error": str(exc)[:240],
            },
        )
        return


def _join_action_for_target(target: WarmupTarget) -> str:
    if target.target_type == WarmupTarget.TargetType.FOLDER:
        return WarmupAction.ActionType.JOIN_FOLDER
    return WarmupAction.ActionType.JOIN_CHANNEL


def _policy_allows_join(policy: WarmupPolicy, target: WarmupTarget) -> bool:
    if target.target_type == WarmupTarget.TargetType.FOLDER:
        return policy.allow_folder_one_click
    if target.visibility == WarmupTarget.Visibility.PRIVATE and not policy.allow_private_join:
        return False
    return policy.enable_join_groups and policy.allow_public_gradual_join


def _append_action(
    actions: list[WarmupAction],
    *,
    plan: WarmupPlan,
    account: TelegramAccount,
    target: WarmupTarget,
    action_type: str,
    scheduled_for,
    now,
    metadata: dict[str, object] | None = None,
) -> None:
    actions.append(
        WarmupAction(
            owner=plan.owner,
            plan=plan,
            account=account,
            target=target,
            action_type=action_type,
            scheduled_for=scheduled_for,
            delay_seconds=max(0, int((scheduled_for - now).total_seconds())),
            metadata=metadata or {},
        )
    )


def _scenario_metadata(policy: WarmupPolicy, action_type: str) -> dict[str, object]:
    metadata: dict[str, object] = {
        "policy_id": policy.id,
        "behavior_profile": policy.behavior_profile,
        "warmup_source": policy.warmup_source,
    }
    if action_type == WarmupAction.ActionType.MESSAGE_SEARCH:
        metadata["query"] = (policy.search_query or "").strip()
    elif action_type == WarmupAction.ActionType.INLINE_BOT_CHECK:
        metadata["bot"] = policy.inline_bot_username or "gif"
        metadata["query"] = (policy.search_query or "").strip()
    elif action_type == WarmupAction.ActionType.GIF_SEARCH:
        metadata["query"] = (policy.search_query or "").strip()
    elif action_type == WarmupAction.ActionType.SAVED_NOTE:
        metadata["note"] = "Нотатка"
    return metadata


def _enabled_cycle_action_types(policy: WarmupPolicy) -> list[str]:
    action_types = [action_type for flag_name, action_type in SCENARIO_FLAGS if getattr(policy, flag_name)]
    if policy.enable_read_channels:
        action_types.append(WarmupAction.ActionType.READ)
    if not (policy.search_query or "").strip():
        action_types = [
            action_type
            for action_type in action_types
            if action_type
            not in {
                WarmupAction.ActionType.MESSAGE_SEARCH,
                WarmupAction.ActionType.GIF_SEARCH,
                WarmupAction.ActionType.INLINE_BOT_CHECK,
            }
        ]
    if not action_types:
        return [WarmupAction.ActionType.VIEW_DIALOGS]
    return action_types


def _account_sent_messages_today(account: TelegramAccount, now) -> int:
    day_start = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.get_current_timezone())
    return WarmupAction.objects.filter(
        account=account,
        action_type__in=MESSAGE_SENDING_ACTION_TYPES,
        status__in=[WarmupAction.Status.SUCCEEDED, WarmupAction.Status.QUEUED, WarmupAction.Status.RUNNING],
        scheduled_for__gte=day_start,
    ).count()


def _filter_message_sending_actions(policy: WarmupPolicy, action_types: list[str], *, sent_messages_today: int) -> list[str]:
    if policy.messages_per_day <= 0 or sent_messages_today >= policy.messages_per_day:
        filtered = [action_type for action_type in action_types if action_type not in MESSAGE_SENDING_ACTION_TYPES]
        return filtered or [WarmupAction.ActionType.VIEW_DIALOGS]
    remaining = policy.messages_per_day - sent_messages_today
    sending_seen = 0
    filtered = []
    for action_type in action_types:
        if action_type in MESSAGE_SENDING_ACTION_TYPES:
            sending_seen += 1
            if sending_seen > remaining:
                continue
        filtered.append(action_type)
    return filtered or [WarmupAction.ActionType.VIEW_DIALOGS]


def _pick_cycle_action_type(policy: WarmupPolicy, *, previous_action_type: str | None = None, allow_reaction: bool = True) -> str:
    action_types = _enabled_cycle_action_types(policy)
    limits = clamp_policy(policy)
    if policy.enable_reactions and allow_reaction and random.randint(1, 100) <= limits["reaction_probability"]:
        action_types.append(WarmupAction.ActionType.REACTION)
    if previous_action_type and len(action_types) > 1:
        action_types = [action_type for action_type in action_types if action_type != previous_action_type] or action_types
    return random.choice(action_types)


def _random_cycle_target(plan: WarmupPlan, preferred_target: WarmupTarget | None = None) -> WarmupTarget | None:
    targets = list(plan.targets.filter(status=WarmupTarget.Status.ACTIVE))
    if not targets:
        return None
    if preferred_target and preferred_target in targets and random.randint(1, 100) <= 45:
        return preferred_target
    return random.choice(targets)


def _ordered_plan_targets(plan: WarmupPlan, policy: WarmupPolicy, daily_limit: int) -> list[WarmupTarget]:
    targets = list(plan.targets.filter(status=WarmupTarget.Status.ACTIVE))
    folders = [target for target in targets if target.target_type == WarmupTarget.TargetType.FOLDER]
    channels = [target for target in targets if target.target_type != WarmupTarget.TargetType.FOLDER]
    random.shuffle(folders)
    random.shuffle(channels)
    if folders and policy.allow_folder_one_click:
        return folders + channels[:daily_limit]
    return channels[:daily_limit]


def _create_cycle_action(
    *,
    plan: WarmupPlan,
    account: TelegramAccount,
    target: WarmupTarget,
    action_type: str,
    scheduled_for,
    now,
    metadata: dict[str, object] | None = None,
) -> WarmupAction:
    action = WarmupAction.objects.create(
        owner=plan.owner,
        plan=plan,
        account=account,
        target=target,
        action_type=action_type,
        scheduled_for=scheduled_for,
        delay_seconds=max(0, int((scheduled_for - now).total_seconds())),
        metadata=metadata or {},
    )
    schedule_action_dispatch(action)
    return action


def schedule_next_cycle_action(previous_action: WarmupAction, *, after_error: bool = False) -> WarmupAction | None:
    plan = (
        WarmupPlan.objects.select_related("policy")
        .prefetch_related("targets")
        .filter(pk=previous_action.plan_id, status=WarmupPlan.Status.RUNNING)
        .first()
    )
    if plan is None:
        return None
    account = TelegramAccount.objects.filter(pk=previous_action.account_id, is_attached=True).first()
    if account is None or not account.is_connected:
        return None
    if get_account_runtime_block_reason(account):
        return None
    target = _random_cycle_target(plan, previous_action.target)
    if target is None:
        return None

    policy = plan.policy
    now = timezone.now()
    limits = clamp_policy(policy)
    delay_min = policy.retry_min_seconds if after_error else policy.delay_min_seconds
    delay_max = policy.retry_max_seconds if after_error else policy.delay_max_seconds
    enabled_types_count = max(1, len(_enabled_cycle_action_types(policy)))
    session_step_cap = max(20, int((policy.session_duration_minutes * 60) / enabled_types_count))
    if _account_actions_today(account, now) >= limits["actions_per_day"]:
        scheduled_for = _next_day_active_time(policy, now)
    else:
        base_delay = random.randint(delay_min, delay_max)
        if not after_error:
            base_delay = min(base_delay, session_step_cap)
        if policy.random_breaks and random.randint(1, 100) <= 18:
            break_delay = random.randint(900, 3600)
            if not after_error:
                break_delay = min(break_delay, max(30, session_step_cap))
            base_delay += break_delay
        if _account_actions_this_hour(account, now) >= limits["actions_per_hour"]:
            next_hour = timezone.localtime(now + timedelta(hours=1)).replace(minute=random.randint(0, 20), second=0, microsecond=0)
            scheduled_for = next_active_time(policy, next_hour.astimezone(timezone.get_current_timezone()))
        else:
            scheduled_for = next_active_time(policy, now + timedelta(seconds=base_delay))
    day_start = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.get_current_timezone())
    reactions_today = WarmupAction.objects.filter(
        account=account,
        action_type=WarmupAction.ActionType.REACTION,
        status=WarmupAction.Status.SUCCEEDED,
        finished_at__gte=day_start,
    ).count()
    action_types = _enabled_cycle_action_types(policy)
    action_types = _filter_message_sending_actions(
        policy,
        action_types,
        sent_messages_today=_account_sent_messages_today(account, now),
    )
    if policy.enable_reactions and reactions_today < policy.max_reactions_per_day and random.randint(1, 100) <= limits["reaction_probability"]:
        action_types.append(WarmupAction.ActionType.REACTION)
    if previous_action.action_type and len(action_types) > 1:
        action_types = [action_type for action_type in action_types if action_type != previous_action.action_type] or action_types
    action_type = random.choice(action_types)
    metadata = _scenario_metadata(policy, action_type)
    if action_type == WarmupAction.ActionType.REACTION:
        metadata["reaction"] = random.choice(REACTIONS)
    metadata.update({"cycle": True, "previous_action_id": previous_action.id})
    return _create_cycle_action(
        plan=plan,
        account=account,
        target=target,
        action_type=action_type,
        scheduled_for=scheduled_for,
        now=now,
        metadata=metadata,
    )


@transaction.atomic
def start_warmup_plan(plan: WarmupPlan) -> WarmupPlan:
    plan = (
        WarmupPlan.objects.select_for_update()
        .select_related("policy")
        .prefetch_related("accounts", "targets")
        .get(pk=plan.pk)
    )
    if plan.status == WarmupPlan.Status.RUNNING:
        return plan

    policy = plan.policy
    limits = clamp_policy(policy)
    now = timezone.now()
    actions: list[WarmupAction] = []

    for account in plan.accounts.all():
        if not account.is_connected:
            continue
        daily_limit = random.randint(limits["daily_join_min"], limits["daily_join_max"])
        targets = _ordered_plan_targets(plan, policy, daily_limit)
        cursor = now
        planned_actions_today = 0

        for target in targets:
            if planned_actions_today >= limits["actions_per_day"]:
                break
            join_action_type = _join_action_for_target(target)
            if _policy_allows_join(policy, target):
                if target.target_type == WarmupTarget.TargetType.FOLDER and policy.allow_folder_one_click:
                    join_at = next_active_time(policy, now)
                else:
                    join_at = next_active_time(
                        policy,
                        cursor + timedelta(seconds=random.randint(policy.delay_min_seconds, policy.delay_max_seconds)),
                    )
                _append_action(
                    actions,
                    plan=plan,
                    account=account,
                    target=target,
                    action_type=join_action_type,
                    scheduled_for=join_at,
                    now=now,
                    metadata={
                        "policy_id": policy.id,
                        "behavior_profile": policy.behavior_profile,
                        "join_mode": "folder_one_click" if join_action_type == WarmupAction.ActionType.JOIN_FOLDER else "gradual_channel",
                    },
                )
                cursor = join_at
                planned_actions_today += 1

        warmup_target = _random_cycle_target(plan) or (targets[0] if targets else None)
        if warmup_target is not None and planned_actions_today < limits["actions_per_day"]:
            day_start = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.get_current_timezone())
            sent_messages_today = _account_sent_messages_today(account, now)
            reactions_today = WarmupAction.objects.filter(
                account=account,
                action_type=WarmupAction.ActionType.REACTION,
                status=WarmupAction.Status.SUCCEEDED,
                finished_at__gte=day_start,
            ).count()
            action_types = _enabled_cycle_action_types(policy)
            action_types = _filter_message_sending_actions(
                policy,
                action_types,
                sent_messages_today=sent_messages_today,
            )
            if (
                policy.enable_reactions
                and reactions_today < limits["max_reactions_per_day"]
                and WarmupAction.ActionType.REACTION not in action_types
            ):
                action_types.append(WarmupAction.ActionType.REACTION)
            random.shuffle(action_types)
            remaining_slots = max(0, limits["actions_per_day"] - planned_actions_today)
            if remaining_slots == 0:
                continue
            action_types = action_types[:remaining_slots]
            if (
                policy.enable_reactions
                and reactions_today < limits["max_reactions_per_day"]
                and WarmupAction.ActionType.REACTION not in action_types
                and action_types
            ):
                action_types[-1] = WarmupAction.ActionType.REACTION
            session_window_seconds = max(60, policy.session_duration_minutes * 60)
            session_started_at = cursor

            for index, action_type in enumerate(action_types):
                if planned_actions_today >= limits["actions_per_day"]:
                    break
                if action_type in MESSAGE_SENDING_ACTION_TYPES and sent_messages_today >= policy.messages_per_day:
                    continue
                if action_type == WarmupAction.ActionType.READ:
                    metadata = _scenario_metadata(policy, action_type)
                    metadata["read_seconds"] = random.randint(policy.read_min_seconds, policy.read_max_seconds)
                elif action_type == WarmupAction.ActionType.REACTION:
                    metadata = _scenario_metadata(policy, action_type)
                    metadata["reaction"] = random.choice(REACTIONS)
                    reactions_today += 1
                else:
                    metadata = _scenario_metadata(policy, action_type)
                slot_start = int((session_window_seconds * index) / max(1, len(action_types)))
                slot_end = int((session_window_seconds * (index + 1)) / max(1, len(action_types)))
                min_offset = 0 if index == 0 and planned_actions_today else 5
                offset_seconds = random.randint(max(min_offset, slot_start), max(min_offset, slot_end - 1))
                cursor = next_active_time(policy, session_started_at + timedelta(seconds=offset_seconds))
                metadata["cycle"] = True
                metadata["initial_cycle"] = True
                _append_action(
                    actions,
                    plan=plan,
                    account=account,
                    target=warmup_target,
                    action_type=action_type,
                    scheduled_for=cursor,
                    now=now,
                    metadata=metadata,
                )
                planned_actions_today += 1
                if action_type in MESSAGE_SENDING_ACTION_TYPES:
                    sent_messages_today += 1

    WarmupAction.objects.filter(plan=plan, status=WarmupAction.Status.QUEUED).delete()
    created = WarmupAction.objects.bulk_create(actions)
    plan.status = WarmupPlan.Status.RUNNING
    plan.started_at = now
    plan.completed_at = None
    plan.save(update_fields=["status", "started_at", "completed_at", "updated_at"])

    for action in created:
        schedule_action_dispatch(action)
    return plan


def run_due_warmup_actions(*, owner, limit: int = 20, force: bool = False) -> dict[str, int]:
    queryset = WarmupAction.objects.filter(
        owner=owner,
        status=WarmupAction.Status.QUEUED,
        plan__status=WarmupPlan.Status.RUNNING,
    )
    if not force:
        queryset = queryset.filter(scheduled_for__lte=timezone.now())

    action_ids = list(queryset.order_by("scheduled_for").values_list("id", flat=True)[:limit])
    processed = 0
    for action_id in action_ids:
        execute_warmup_action(action_id)
        processed += 1

    log_warmup_event(
        owner=owner,
        level=WarmupLog.Level.INFO,
        message=f"🧪 Ручний запуск прогріву: оброблено {processed} дій. Force={bool(force)}, limit={limit}.",
        metadata={"processed": processed, "force": force, "limit": limit},
    )
    return {"processed": processed, "force": int(force), "limit": limit}


def _revoke_celery_tasks(task_ids: list[str]) -> int:
    task_ids = [task_id for task_id in task_ids if task_id]
    if not task_ids:
        return 0
    try:
        from config.celery import app as celery_app

        celery_app.control.revoke(task_ids, terminate=False)
    except Exception:
        return 0
    return len(task_ids)


def _decode_celery_message(raw_message: bytes | str) -> dict[str, object] | None:
    if isinstance(raw_message, bytes):
        raw_message = raw_message.decode("utf-8", errors="ignore")
    try:
        payload = json.loads(raw_message)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return payload[0]
    return payload if isinstance(payload, dict) else None


def _is_warmup_celery_message(raw_message: bytes | str) -> bool:
    payload = _decode_celery_message(raw_message)
    if not payload:
        return False
    headers = payload.get("headers")
    if isinstance(headers, dict) and headers.get("task") in WARMUP_TASK_NAMES:
        return True
    body = payload.get("body")
    if isinstance(body, dict) and body.get("task") in WARMUP_TASK_NAMES:
        return True
    return False


def purge_warmup_messages_from_redis() -> dict[str, int]:
    queue_names: set[str] = {"celery"}
    removed = 0
    scanned = 0
    try:
        client = redis.from_url(settings.CELERY_BROKER_URL)
        for key in client.scan_iter(match="celery*"):
            key_type = client.type(key)
            if key_type == b"list" or key_type == "list":
                queue_names.add(key.decode("utf-8") if isinstance(key, bytes) else key)
        for queue_name in queue_names:
            messages = client.lrange(queue_name, 0, -1)
            if not messages:
                continue
            keep = []
            for message in messages:
                scanned += 1
                if _is_warmup_celery_message(message):
                    removed += 1
                else:
                    keep.append(message)
            pipe = client.pipeline()
            pipe.delete(queue_name)
            if keep:
                pipe.rpush(queue_name, *keep)
            pipe.execute()
        unacked_messages = client.hgetall("unacked")
        if unacked_messages:
            pipe = client.pipeline()
            for delivery_tag, message in unacked_messages.items():
                scanned += 1
                if not _is_warmup_celery_message(message):
                    continue
                removed += 1
                pipe.hdel("unacked", delivery_tag)
                pipe.zrem("unacked_index", delivery_tag)
            pipe.execute()
    except Exception:
        return {"redis_scanned": scanned, "redis_removed": removed, "redis_error": 1}
    return {"redis_scanned": scanned, "redis_removed": removed, "redis_error": 0}


@transaction.atomic
def clear_warmup_actions(
    *,
    owner,
    mode: str = WarmupAction.Status.QUEUED,
    clear_logs: bool = False,
    purge_redis: bool = True,
) -> dict[str, int | str]:
    allowed_modes = {
        WarmupAction.Status.QUEUED,
        WarmupAction.Status.RUNNING,
        WarmupAction.Status.FAILED,
        WarmupAction.Status.SKIPPED,
        "all",
    }
    if mode not in allowed_modes:
        raise ValueError("Unsupported warmup action clear mode.")

    queryset = WarmupAction.objects.filter(owner=owner)
    if mode != "all":
        queryset = queryset.filter(status=mode)

    action_ids = list(queryset.values_list("id", flat=True))
    task_ids = list(queryset.exclude(celery_task_id="").values_list("celery_task_id", flat=True))
    before_counts = {
        item["status"]: item["count"]
        for item in queryset.values("status").annotate(count=Count("id"))
    }
    deleted_logs = 0
    if clear_logs:
        log_queryset = WarmupLog.objects.filter(owner=owner)
        if mode != "all":
            log_queryset = log_queryset.filter(Q(action_id__in=action_ids) | Q(action__isnull=True))
        deleted_logs, _ = log_queryset.delete()
    deleted_count, _ = queryset.delete()
    revoked_count = _revoke_celery_tasks(task_ids)
    redis_payload = purge_warmup_messages_from_redis() if purge_redis else {"redis_scanned": 0, "redis_removed": 0, "redis_error": 0}

    affected_plans = 0
    if mode in {WarmupAction.Status.QUEUED, WarmupAction.Status.RUNNING, "all"}:
        running_plans = WarmupPlan.objects.filter(owner=owner, status=WarmupPlan.Status.RUNNING)
        for plan in running_plans:
            if plan.actions.filter(status__in=[WarmupAction.Status.QUEUED, WarmupAction.Status.RUNNING]).exists():
                continue
            plan.status = WarmupPlan.Status.PAUSED
            plan.save(update_fields=["status", "updated_at"])
            affected_plans += 1

    cleanup_message = (
        f"🧹 Очищено прогрів: прибрано {deleted_count} дій і {deleted_logs} логів. "
        f"Старі заплановані дії зупинено, режим «{mode}»."
    )
    cleanup_metadata = {
        "mode": mode,
        "deleted": deleted_count,
        "deleted_logs": deleted_logs,
        "revoked": revoked_count,
        "before_counts": before_counts,
        "paused_plans": affected_plans,
        **redis_payload,
    }
    if clear_logs:
        publish_log_event({"level": "warning", "source": "warmup", "message": cleanup_message, **cleanup_metadata})
    else:
        log_warmup_event(owner=owner, level=WarmupLog.Level.WARNING, message=cleanup_message, metadata=cleanup_metadata)
    return {
        "mode": mode,
        "deleted": deleted_count,
        "deleted_logs": deleted_logs,
        "revoked": revoked_count,
        "paused_plans": affected_plans,
        **redis_payload,
    }


@transaction.atomic
def pause_warmup_plan(plan: WarmupPlan) -> WarmupPlan:
    WarmupAction.objects.filter(plan=plan, status=WarmupAction.Status.QUEUED).update(status=WarmupAction.Status.SKIPPED, error="Plan paused.")
    plan.status = WarmupPlan.Status.PAUSED
    plan.save(update_fields=["status", "updated_at"])
    log_warmup_event(owner=plan.owner, level=WarmupLog.Level.WARNING, plan=plan, message=f"⏸️ План «{plan.name}» поставлено на паузу. Усі queued дії позначені як пропущені.")
    return plan


@transaction.atomic
def stop_warmup_plan(plan: WarmupPlan, *, purge_redis: bool = True) -> dict[str, int | str]:
    plan = WarmupPlan.objects.select_for_update().get(pk=plan.pk)
    action_queryset = WarmupAction.objects.filter(plan=plan)
    task_ids = list(action_queryset.exclude(celery_task_id="").values_list("celery_task_id", flat=True))
    action_count = action_queryset.count()
    log_count = WarmupLog.objects.filter(plan=plan).count()
    plan_id = plan.id
    plan_name = plan.name

    revoked_count = _revoke_celery_tasks(task_ids)
    redis_payload = purge_warmup_messages_from_redis() if purge_redis else {"redis_scanned": 0, "redis_removed": 0, "redis_error": 0}
    plan.delete()

    message = (
        f"🛑 Stop: план «{plan_name}» повністю видалено із прогріву. "
        f"Видалено {action_count} дій, {log_count} логів, відкликано {revoked_count} Celery task id."
    )
    metadata = {
        "plan_id": plan_id,
        "deleted_actions": action_count,
        "deleted_logs": log_count,
        "revoked": revoked_count,
        **redis_payload,
    }
    publish_log_event({"level": "warning", "source": "warmup", "message": message, **metadata})
    return {"plan_id": plan_id, "deleted_actions": action_count, "deleted_logs": log_count, "revoked": revoked_count, **redis_payload}


def _target_ref(target: WarmupTarget) -> str:
    return target.value


def _chat_title(chat) -> str:
    title = getattr(chat, "title", "") or " ".join(
        filter(None, [getattr(chat, "first_name", ""), getattr(chat, "last_name", "")])
    ).strip()
    username = getattr(chat, "username", "") or ""
    if title and username:
        return f"{title} (@{username})"
    return title or (f"@{username}" if username else str(getattr(chat, "id", "unknown")))


def _chat_ref(chat):
    return getattr(chat, "id", None) or getattr(chat, "username", None)


async def _dialog_snapshots(app, limit: int = 10) -> list[dict[str, object]]:
    dialogs: list[dict[str, object]] = []
    async for dialog in app.get_dialogs(limit=limit):
        chat = getattr(dialog, "chat", None)
        if chat is None:
            continue
        dialogs.append(
            {
                "id": getattr(chat, "id", None),
                "title": _chat_title(chat),
                "type": str(getattr(chat, "type", "") or ""),
                "username": getattr(chat, "username", "") or "",
                "unread_messages_count": getattr(dialog, "unread_messages_count", 0),
                "unread_mentions_count": getattr(dialog, "unread_mentions_count", 0),
            }
        )
    return dialogs


async def _folder_dialog_chats(app, limit: int = 5) -> list[object]:
    chats = []
    async for dialog in app.get_dialogs(limit=limit):
        chat = getattr(dialog, "chat", None)
        if chat is not None:
            chats.append(chat)
    return chats


async def _subscription_chats(app, limit: int = 30, sample_size: int = 5) -> list[object]:
    chats = []
    async for dialog in app.get_dialogs(limit=limit):
        chat = getattr(dialog, "chat", None)
        if chat is not None:
            chats.append(chat)
    random.shuffle(chats)
    return chats[:sample_size]


def _warmup_sample_size(max_size: int = WARMUP_CHAT_SAMPLE_MAX) -> int:
    upper = max(WARMUP_CHAT_SAMPLE_MIN, max_size)
    return random.randint(WARMUP_CHAT_SAMPLE_MIN, upper)


async def _target_chats(app, target: WarmupTarget, *, folder_limit: int = 5) -> list[object]:
    if target.target_type == WarmupTarget.TargetType.FOLDER:
        return await _folder_dialog_chats(app, limit=folder_limit)
    return [await app.get_chat(_target_ref(target))]


async def _warmup_chats(app, target: WarmupTarget, source: str, *, folder_limit: int = 5, subscription_limit: int = 30) -> list[object]:
    if source == WarmupPolicy.WarmupSource.SUBSCRIPTIONS:
        sample_size = min(folder_limit, _warmup_sample_size(folder_limit))
        chats = await _subscription_chats(app, limit=subscription_limit, sample_size=sample_size)
        if chats:
            return chats
        # Fallback: account has no viable subscriptions yet; use target/folder source so actions are real.
        return await _target_chats(app, target, folder_limit=folder_limit)
    return await _target_chats(app, target, folder_limit=folder_limit)


def _chat_history_ref(chat):
    return getattr(chat, "username", None) or getattr(chat, "id", None)


async def _first_message_from_chats(app, chats: list[object]):
    for chat in chats:
        chat_ref = _chat_history_ref(chat)
        if chat_ref is None:
            continue
        async for message in app.get_chat_history(chat_ref, limit=1):
            return chat_ref, chat, message
    return None, None, None


def _extract_addlist_slug(value: str) -> str:
    match = re.search(r"(?:https?://)?t\.me/addlist/([A-Za-z0-9_\-]+)", value)
    if not match:
        raise RuntimeError("Некоректне посилання addlist. Очікується формат https://t.me/addlist/...")
    return match.group(1)


def _raw_peer_title(peer, *, chats_by_id: dict[int, object], users_by_id: dict[int, object]) -> str:
    if isinstance(peer, raw.types.PeerChannel):
        chat = chats_by_id.get(peer.channel_id)
        return getattr(chat, "title", "") or getattr(chat, "username", "") or str(peer.channel_id)
    if isinstance(peer, raw.types.PeerChat):
        chat = chats_by_id.get(peer.chat_id)
        return getattr(chat, "title", "") or str(peer.chat_id)
    if isinstance(peer, raw.types.PeerUser):
        user = users_by_id.get(peer.user_id)
        title = " ".join(filter(None, [getattr(user, "first_name", ""), getattr(user, "last_name", "")])).strip()
        return title or getattr(user, "username", "") or str(peer.user_id)
    return str(peer)


def _raw_peer_key(peer) -> tuple[str, int] | None:
    if isinstance(peer, raw.types.PeerChannel):
        return ("channel", peer.channel_id)
    if isinstance(peer, raw.types.PeerChat):
        return ("chat", peer.chat_id)
    if isinstance(peer, raw.types.PeerUser):
        return ("user", peer.user_id)
    return None


async def _dialog_peer_keys(app, limit: int = 500) -> set[tuple[str, int]]:
    keys: set[tuple[str, int]] = set()
    if not hasattr(app, "get_dialogs"):
        return keys
    async for dialog in app.get_dialogs(limit=limit):
        chat = getattr(dialog, "chat", None)
        if chat is None:
            continue
        chat_type = str(getattr(chat, "type", "") or "")
        chat_id = abs(int(getattr(chat, "id", 0) or 0))
        if not chat_id:
            continue
        if chat_type in {"channel", "supergroup"}:
            keys.add(("channel", chat_id))
        elif chat_type in {"group"}:
            keys.add(("chat", chat_id))
        else:
            keys.add(("user", chat_id))
    return keys


def _expected_peer_keys(peers: list[object]) -> set[tuple[str, int]]:
    keys: set[tuple[str, int]] = set()
    for peer in peers:
        key = _raw_peer_key(peer)
        if key is not None:
            keys.add(key)
    return keys


async def _confirm_joined_peer_count(
    app,
    *,
    peers: list[object],
    before_keys: set[tuple[str, int]],
    attempts: int = 6,
    delay_seconds: float = 0.7,
) -> int:
    expected_new = _expected_peer_keys(peers) - before_keys
    if not expected_new:
        return 0
    confirmed = 0
    for attempt in range(attempts):
        after_keys = await _dialog_peer_keys(app)
        confirmed = sum(1 for key in expected_new if key in after_keys)
        if confirmed > 0 or attempt == attempts - 1:
            return confirmed
        await asyncio.sleep(delay_seconds)
    return confirmed


def _raw_peer_to_input_peer(peer, *, chats_by_id: dict[int, object], users_by_id: dict[int, object]):
    if isinstance(peer, raw.types.PeerChannel):
        chat = chats_by_id.get(peer.channel_id)
        access_hash = getattr(chat, "access_hash", None)
        if access_hash is None:
            raise RuntimeError(f"Немає access_hash для каналу/групи {peer.channel_id} з addlist.")
        return raw.types.InputPeerChannel(channel_id=peer.channel_id, access_hash=access_hash)
    if isinstance(peer, raw.types.PeerChat):
        return raw.types.InputPeerChat(chat_id=peer.chat_id)
    if isinstance(peer, raw.types.PeerUser):
        user = users_by_id.get(peer.user_id)
        access_hash = getattr(user, "access_hash", None)
        if access_hash is None:
            raise RuntimeError(f"Немає access_hash для user {peer.user_id} з addlist.")
        return raw.types.InputPeerUser(user_id=peer.user_id, access_hash=access_hash)
    raise RuntimeError(f"Непідтримуваний peer у addlist: {type(peer).__name__}")


async def _join_chatlist_invite_operation(app, target: WarmupTarget):
    slug = _extract_addlist_slug(target.value)
    invite = await app.invoke(raw.functions.chatlists.CheckChatlistInvite(slug=slug))
    before_keys = await _dialog_peer_keys(app)
    chats_by_id = {getattr(chat, "id", None): chat for chat in getattr(invite, "chats", []) or []}
    users_by_id = {getattr(user, "id", None): user for user in getattr(invite, "users", []) or []}
    peers = list(getattr(invite, "peers", []) or [])
    missing_peers = list(getattr(invite, "missing_peers", []) or [])
    seen_keys = {key for key in (_raw_peer_key(peer) for peer in peers) if key is not None}
    for peer in missing_peers:
        key = _raw_peer_key(peer)
        if key is None or key in seen_keys:
            continue
        peers.append(peer)
        seen_keys.add(key)
    already_count = len(getattr(invite, "already_peers", []) or [])

    if not peers:
        return {
            "slug": slug,
            "folder_title": getattr(invite, "title", target.title),
            "joined_count": 0,
            "already_count": already_count,
            "peer_titles": [],
            "already": True,
        }

    input_peers = []
    skipped_peers = []
    for peer in peers:
        try:
            input_peers.append(_raw_peer_to_input_peer(peer, chats_by_id=chats_by_id, users_by_id=users_by_id))
        except RuntimeError:
            skipped_peers.append(_raw_peer_title(peer, chats_by_id=chats_by_id, users_by_id=users_by_id))
    if not input_peers:
        raise RuntimeError("У папці addlist немає peer-ів, які можна додати через API (відсутні access_hash).")
    await app.invoke(raw.functions.chatlists.JoinChatlistInvite(slug=slug, peers=input_peers))
    joined_confirmed = await _confirm_joined_peer_count(app, peers=peers, before_keys=before_keys)
    return {
        "slug": slug,
        "folder_title": getattr(invite, "title", target.title),
        "joined_count": len(input_peers),
        "joined_confirmed_count": joined_confirmed,
        "already_count": already_count,
        "skipped_count": len(skipped_peers),
        "skipped_titles": skipped_peers[:20],
        "peer_titles": [
            _raw_peer_title(peer, chats_by_id=chats_by_id, users_by_id=users_by_id)
            for peer in peers[:20]
        ],
    }


async def _join_operation(app, target: WarmupTarget):
    if target.target_type == WarmupTarget.TargetType.FOLDER:
        result = await _join_chatlist_invite_operation(app, target)
        joined = int(result.get("joined_count") or 0)
        confirmed = int(result.get("joined_confirmed_count") or 0)
        if joined > 0 and confirmed == 0:
            raise RuntimeError(
                "Папку addlist прийнято, але Telegram не показав нових чатів у діалогах. "
                "Перевірте slug addlist/доступність запрошених чатів і повторіть."
            )
        return result

    chat = await app.join_chat(_target_ref(target))
    return {
        "id": getattr(chat, "id", None),
        "title": getattr(chat, "title", "") or "",
        "username": getattr(chat, "username", "") or "",
        "type": str(getattr(chat, "type", "") or ""),
    }


async def _read_operation(app, target: WarmupTarget, source: str = WarmupPolicy.WarmupSource.TARGETS):
    if source == WarmupPolicy.WarmupSource.SUBSCRIPTIONS or target.target_type == WarmupTarget.TargetType.FOLDER:
        chats = await _warmup_chats(app, target, source, folder_limit=WARMUP_CHAT_SAMPLE_MAX)
        results = []
        total_messages = 0
        for chat in chats:
            chat_ref = _chat_ref(chat)
            if chat_ref is None:
                continue
            count = 0
            async for _message in app.get_chat_history(chat_ref, limit=random.randint(1, 5)):
                count += 1
            if count:
                await app.read_chat_history(chat_ref)
            total_messages += count
            results.append({"title": _chat_title(chat), "messages": count})
        return {"messages": total_messages, "chats": results}

    messages = []
    async for message in app.get_chat_history(_target_ref(target), limit=random.randint(1, 5)):
        messages.append(message)
    if messages:
        await app.read_chat_history(_target_ref(target))
    chat = await app.get_chat(_target_ref(target))
    return {"messages": len(messages), "chats": [{"title": _chat_title(chat), "messages": len(messages)}]}


async def _reaction_operation(app, target: WarmupTarget, reaction: str, source: str = WarmupPolicy.WarmupSource.TARGETS):
    chat_ref, chat, message = await _first_message_from_chats(app, await _warmup_chats(app, target, source))
    if message is None:
        return {"message_id": None, "reaction": reaction}
    await app.send_reaction(chat_ref, message.id, reaction)
    return {"message_id": message.id, "reaction": reaction, "chat": _chat_title(chat)}


async def _view_dialogs_operation(app):
    dialogs = await _dialog_snapshots(app, limit=_warmup_sample_size())
    return {"dialogs": len(dialogs), "chats": dialogs}


async def _account_dialog_operation(app, action: WarmupAction | None = None):
    dialogs = await _dialog_snapshots(app, limit=12)
    peers = [dialog["title"] for dialog in dialogs if dialog.get("title")]
    if action is None:
        return {"checked": True, "dialogs": len(dialogs), "peers": peers[:8]}

    account_peers = list(
        action.plan.accounts.exclude(pk=action.account_id).filter(
            is_attached=True,
            auth_state=TelegramAccount.AuthState.CONNECTED,
        )
    )
    if not account_peers:
        return {
            "checked": True,
            "dialogs": len(dialogs),
            "peers": peers[:8],
            "sent": False,
            "reason": "потрібно 2+ підключені акаунти у плані",
        }
    random.shuffle(account_peers)
    text = random.choice(("Привіт", "На зв'язку", "Ок"))
    errors = []
    for peer_account in account_peers:
        peer_ref = peer_account.telegram_username or peer_account.telegram_user_id or peer_account.phone_number
        if not peer_ref:
            errors.append(f"{peer_account.label}: немає username/id/phone")
            continue
        if peer_account.telegram_username:
            peer_ref = peer_account.telegram_username.lstrip("@")
        try:
            sent = await app.send_message(peer_ref, text)
        except Exception as exc:
            errors.append(f"{peer_account.label}: {str(exc)[:120]}")
            continue
        return {
            "checked": True,
            "dialogs": len(dialogs),
            "peers": peers[:8],
            "sent": True,
            "peer": peer_account.telegram_username or peer_account.label,
            "peer_account_id": peer_account.id,
            "text": text,
            "message_id": getattr(sent, "id", None),
        }
    return {
        "checked": True,
        "dialogs": len(dialogs),
        "peers": peers[:8],
        "sent": False,
        "reason": "; ".join(errors[:3]) or "немає доступного peer для діалогу",
    }


async def _channel_scroll_operation(app, target: WarmupTarget, source: str = WarmupPolicy.WarmupSource.TARGETS):
    if source == WarmupPolicy.WarmupSource.SUBSCRIPTIONS or target.target_type == WarmupTarget.TargetType.FOLDER:
        chats = await _warmup_chats(app, target, source, folder_limit=WARMUP_CHAT_SAMPLE_MAX)
        results = []
        total_messages = 0
        for chat in chats:
            chat_ref = _chat_ref(chat)
            if chat_ref is None:
                continue
            count = 0
            async for _message in app.get_chat_history(chat_ref, limit=random.randint(5, 15)):
                count += 1
            total_messages += count
            results.append({"title": _chat_title(chat), "scrolled_messages": count})
        return {"scrolled_messages": total_messages, "chats": results}

    count = 0
    async for _message in app.get_chat_history(_target_ref(target), limit=random.randint(5, 15)):
        count += 1
    chat = await app.get_chat(_target_ref(target))
    return {"scrolled_messages": count, "chats": [{"title": _chat_title(chat), "scrolled_messages": count}]}


async def _mark_read_operation(app, target: WarmupTarget, source: str = WarmupPolicy.WarmupSource.TARGETS):
    if source == WarmupPolicy.WarmupSource.SUBSCRIPTIONS or target.target_type == WarmupTarget.TargetType.FOLDER:
        chats = await _warmup_chats(app, target, source, folder_limit=WARMUP_CHAT_SAMPLE_MAX)
        marked = []
        for chat in chats:
            chat_ref = _chat_ref(chat)
            if chat_ref is None:
                continue
            await app.read_chat_history(chat_ref)
            marked.append(_chat_title(chat))
        return {"marked_read": True, "chats": marked}

    await app.read_chat_history(_target_ref(target))
    chat = await app.get_chat(_target_ref(target))
    return {"marked_read": True, "chats": [_chat_title(chat)]}


async def _message_search_operation(app, target: WarmupTarget, query: str, source: str = WarmupPolicy.WarmupSource.TARGETS):
    total = 0
    results = []
    for chat in await _warmup_chats(app, target, source, folder_limit=WARMUP_CHAT_SAMPLE_MAX):
        chat_ref = _chat_history_ref(chat)
        if chat_ref is None:
            continue
        count = 0
        async for _message in app.search_messages(chat_ref, query=query, limit=5):
            count += 1
        total += count
        results.append({"title": _chat_title(chat), "matches": count})
    return {"query": query, "matches": total, "chats": results}


async def _first_message(app, target: WarmupTarget):
    _chat_ref_value, _chat, message = await _first_message_from_chats(app, await _target_chats(app, target))
    return message


async def _forward_message_operation(app, target: WarmupTarget, source: str = WarmupPolicy.WarmupSource.TARGETS):
    chat_ref, chat, message = await _first_message_from_chats(app, await _warmup_chats(app, target, source))
    if message is None:
        return {"forwarded": False, "reason": "empty_history"}
    preview = ((getattr(message, "text", None) or getattr(message, "caption", None) or "") or "").strip()
    if preview:
        preview = preview[:120]
    try:
        await app.forward_messages("me", chat_ref, message.id)
    except Exception as exc:
        error_text = str(exc)
        if "CHAT_FORWARDS_RESTRICTED" not in error_text:
            raise
        fallback_text = (
            "Forward restricted source\n"
            f"chat: {_chat_title(chat)}\n"
            f"message_id: {message.id}\n\n"
            f"{preview or '[media/no text]'}"
        )
        sent = await app.send_message("me", fallback_text)
        return {
            "forwarded": False,
            "saved_fallback": True,
            "saved_message_id": getattr(sent, "id", None),
            "message_id": message.id,
            "chat": _chat_title(chat),
            "preview": preview,
            "forward_error": error_text[:240],
            "date": str(getattr(message, "date", "")) if getattr(message, "date", None) else "",
        }
    return {
        "forwarded": True,
        "message_id": message.id,
        "chat": _chat_title(chat),
        "preview": preview,
        "date": str(getattr(message, "date", "")) if getattr(message, "date", None) else "",
    }


async def _saved_note_operation(app, note: str):
    sent = await app.send_message("me", note)
    return {"saved_message_id": getattr(sent, "id", None)}


async def _passive_scan_operation(app, target: WarmupTarget, scan_type: str, source: str = WarmupPolicy.WarmupSource.TARGETS):
    seen = 0
    matched = 0
    chats = []
    matched_items = []
    performed_items = []

    def _message_matches(message) -> bool:
        if scan_type == "poll":
            return bool(getattr(message, "poll", None))
        if scan_type == "video":
            return bool(getattr(message, "video", None))
        if scan_type == "voice":
            return bool(getattr(message, "voice", None) or getattr(message, "audio", None))
        if scan_type == "sticker":
            return bool(getattr(message, "sticker", None))
        if scan_type == "link":
            return bool(getattr(message, "web_page", None))
        return False

    async def _perform_message_action(chat_ref, chat, message):
        message_id = getattr(message, "id", None)
        item = {
            "chat": _chat_title(chat),
            "message_id": message_id,
            "media_type": scan_type,
        }
        if hasattr(app, "read_chat_history") and message_id:
            await app.read_chat_history(chat_ref, max_id=message_id)
            item["action"] = "read_chat_history"
        else:
            item["action"] = "matched_only"
        performed_items.append(item)

    for chat in await _warmup_chats(app, target, source, folder_limit=PASSIVE_SCAN_CHAT_LIMIT, subscription_limit=PASSIVE_SCAN_CHAT_LIMIT):
        chat_ref = _chat_history_ref(chat)
        if chat_ref is None:
            continue
        chat_seen = 0
        chat_matched = 0
        async for message in app.get_chat_history(chat_ref, limit=PASSIVE_SCAN_HISTORY_LIMIT):
            seen += 1
            chat_seen += 1
            if _message_matches(message):
                matched += 1
                chat_matched += 1
                if len(matched_items) < 20:
                    matched_items.append({"chat": _chat_title(chat), "message_id": getattr(message, "id", None), "media_type": scan_type})
                if len(performed_items) < PASSIVE_SCAN_PERFORM_LIMIT:
                    await _perform_message_action(chat_ref, chat, message)
        chats.append({"title": _chat_title(chat), "seen": chat_seen, "matched": chat_matched})
        if len(performed_items) >= PASSIVE_SCAN_PERFORM_LIMIT:
            break
    return {
        "scan_type": scan_type,
        "seen": seen,
        "matched": matched,
        "chat_limit": PASSIVE_SCAN_CHAT_LIMIT,
        "history_limit": PASSIVE_SCAN_HISTORY_LIMIT,
        "chats": chats,
        "matched_items": matched_items,
        "performed_items": performed_items,
    }


async def _inline_bot_operation(app, bot_username: str, query: str):
    results = await app.get_inline_bot_results(bot_username, query)
    items = list(getattr(results, "results", []) or [])
    first = items[0] if items else None
    return {
        "bot": bot_username,
        "query": query,
        "results": len(items),
        "first_result_id": getattr(first, "id", None) if first else None,
        "first_result_type": str(getattr(first, "type", "") or "") if first else "",
        "query_id": str(getattr(results, "query_id", "") or ""),
    }


async def _gif_search_operation(app, query: str):
    return await _inline_bot_operation(app, "gif", query)


async def _typing_operation(app, target: WarmupTarget, source: str = WarmupPolicy.WarmupSource.TARGETS):
    from pyrogram.enums import ChatAction

    chats = await _warmup_chats(app, target, source, folder_limit=1)
    if not chats:
        return {"typing": False, "reason": "no_dialogs"}
    chat = chats[0]
    await app.send_chat_action(_chat_history_ref(chat), ChatAction.TYPING)
    return {"typing": True, "chat": _chat_title(chat)}


async def _profile_view_operation(app, target: WarmupTarget, source: str = WarmupPolicy.WarmupSource.TARGETS):
    chats = await _warmup_chats(app, target, source, folder_limit=5)
    if not chats:
        return {"chat_id": None, "title": target.title}
    chat = chats[0]
    return {
        "chat_id": getattr(chat, "id", None),
        "title": getattr(chat, "title", "") or getattr(chat, "username", ""),
        "chats": [_chat_title(item) for item in chats],
    }


async def _story_view_operation(app, target: WarmupTarget, source: str = WarmupPolicy.WarmupSource.TARGETS):
    story_items = []
    checked = 0
    async for dialog in app.get_dialogs(limit=100):
        chat = getattr(dialog, "chat", None)
        if chat is None:
            continue
        checked += 1
        has_stories = bool(getattr(chat, "has_stories", False) or getattr(chat, "has_unread_stories", False))
        stories_max_id = getattr(chat, "stories_max_id", None) or getattr(chat, "max_story_id", None)
        if has_stories or stories_max_id:
            story_items.append(
                {
                    "chat_id": getattr(chat, "id", None),
                    "title": _chat_title(chat),
                    "max_id": stories_max_id,
                }
            )
    if story_items:
        random.shuffle(story_items)
        owner = story_items[0]["title"]
    else:
        owner = "доступних сторіс не знайдено"
    return {
        "checked": True,
        "checked_dialogs": checked,
        "chat_id": story_items[0].get("chat_id") if story_items else None,
        "title": owner,
        "story_owner": owner,
        "stories": len(story_items),
        "story_items": story_items[:10],
    }


async def _settings_check_operation(app):
    me = await app.get_me()
    return {"user_id": getattr(me, "id", None), "username": getattr(me, "username", "") or ""}


async def _trust_boost_operation(app, target: WarmupTarget, source: str = WarmupPolicy.WarmupSource.TARGETS):
    dialogs = await _dialog_snapshots(app, limit=5)
    chats = await _warmup_chats(app, target, source, folder_limit=1)
    chat = chats[0] if chats else None
    profile_checked = _chat_title(chat) if chat else target.title
    return {
        "checked": True,
        "target": _chat_title(chat) if chat else target.title,
        "profile_checked": profile_checked,
        "dialogs": len(dialogs),
        "dialog_titles": [dialog.get("title") for dialog in dialogs if dialog.get("title")][:8],
        "signals": ["перегляд діалогів", "перевірка профілю", "читання без дій"],
    }


async def _scheduled_message_check_operation(app):
    scheduled_at = timezone.now() + timedelta(hours=24)
    text = "Нагадування"
    sent = await app.send_message("me", text, schedule_date=scheduled_at)
    return {
        "scheduled_message_id": getattr(sent, "id", None),
        "scheduled_for": scheduled_at.isoformat(),
        "chat": "Збережене",
        "text": text,
    }


async def _safe_metadata_operation(_app, action: WarmupAction):
    return {"checked": True, "mode": "safe", "action_type": action.action_type}


def _operation_for_action(action: WarmupAction):
    source = _action_warmup_source(action)
    def _query_or_error() -> str:
        query = str(action.metadata.get("query") or "").strip()
        if not query:
            raise RuntimeError("Search query порожній: дію не можна виконати без конкретного запиту.")
        return query

    if action.action_type in {WarmupAction.ActionType.JOIN_CHANNEL, WarmupAction.ActionType.JOIN_FOLDER}:
        return lambda app: _join_operation(app, action.target)
    if action.action_type == WarmupAction.ActionType.READ:
        return lambda app: _read_operation(app, action.target, source)
    if action.action_type == WarmupAction.ActionType.VIEW_DIALOGS:
        return lambda app: _view_dialogs_operation(app)
    if action.action_type == WarmupAction.ActionType.ACCOUNT_DIALOG:
        return lambda app: _account_dialog_operation(app, action)
    if action.action_type == WarmupAction.ActionType.CHANNEL_SCROLL:
        return lambda app: _channel_scroll_operation(app, action.target, source)
    if action.action_type == WarmupAction.ActionType.MARK_READ:
        return lambda app: _mark_read_operation(app, action.target, source)
    if action.action_type == WarmupAction.ActionType.MESSAGE_SEARCH:
        return lambda app: _message_search_operation(app, action.target, _query_or_error(), source)
    if action.action_type == WarmupAction.ActionType.REACTION:
        return lambda app: _reaction_operation(app, action.target, action.metadata.get("reaction") or "👍", source)
    if action.action_type == WarmupAction.ActionType.FORWARD_MESSAGE:
        return lambda app: _forward_message_operation(app, action.target, source)
    if action.action_type == WarmupAction.ActionType.SAVED_NOTE:
        return lambda app: _saved_note_operation(app, action.metadata.get("note") or "Нотатка")
    if action.action_type in PASSIVE_SCAN_ACTIONS:
        return lambda app: _passive_scan_operation(app, action.target, PASSIVE_SCAN_ACTIONS[action.action_type], source)
    if action.action_type == WarmupAction.ActionType.INLINE_BOT_CHECK:
        return lambda app: _inline_bot_operation(
            app,
            action.metadata.get("bot") or "gif",
            _query_or_error(),
        )
    if action.action_type == WarmupAction.ActionType.GIF_SEARCH:
        return lambda app: _gif_search_operation(app, _query_or_error())
    if action.action_type == WarmupAction.ActionType.TYPING_SIMULATION:
        return lambda app: _typing_operation(app, action.target, source)
    if action.action_type == WarmupAction.ActionType.PROFILE_VIEW:
        return lambda app: _profile_view_operation(app, action.target, source)
    if action.action_type == WarmupAction.ActionType.STORY_VIEW:
        return lambda app: _story_view_operation(app, action.target, source)
    if action.action_type == WarmupAction.ActionType.TRUST_BOOST:
        return lambda app: _trust_boost_operation(app, action.target, source)
    if action.action_type in {
        WarmupAction.ActionType.SETTINGS_CHECK,
        WarmupAction.ActionType.GRADUAL_PROFILE_CHECK,
    }:
        return lambda app: _settings_check_operation(app)
    if action.action_type == WarmupAction.ActionType.SCHEDULED_MESSAGE_CHECK:
        return lambda app: _scheduled_message_check_operation(app)
    raise RuntimeError(f"Unsupported warmup action type: {action.action_type}")


def _claim_warmup_action(action_id: int) -> WarmupAction | None:
    with transaction.atomic():
        action = (
            WarmupAction.objects.select_for_update()
            .select_related("account", "target", "plan", "plan__policy")
            .get(pk=action_id)
        )
        if action.status != WarmupAction.Status.QUEUED:
            return None
        # Allow tiny clock/queue jitter so task won't bounce as "queued" and wait for next beat tick.
        if action.scheduled_for > timezone.now() + timedelta(seconds=1):
            return None

        action.status = WarmupAction.Status.RUNNING
        action.started_at = timezone.now()
        action.attempt += 1
        action.error = ""
        action.save(update_fields=["status", "started_at", "attempt", "error", "updated_at"])
        return action


def _finish_warmup_action(action: WarmupAction, *, status: str, error: str = "", metadata: dict[str, object] | None = None) -> WarmupAction:
    with transaction.atomic():
        action = WarmupAction.objects.select_for_update().select_related("plan").get(pk=action.pk)
        action.status = status
        action.error = error
        action.finished_at = timezone.now()
        if metadata is not None:
            action.metadata = metadata
            action.save(update_fields=["status", "error", "metadata", "finished_at", "updated_at"])
        else:
            action.save(update_fields=["status", "error", "finished_at", "updated_at"])
        return action


def execute_warmup_action(action_id: int) -> WarmupAction:
    claimed = _claim_warmup_action(action_id)
    if claimed is None:
        return WarmupAction.objects.select_related("account", "target", "plan", "plan__policy").get(pk=action_id)

    action = WarmupAction.objects.select_related("account", "target", "plan", "plan__policy").get(pk=claimed.pk)
    account = action.account
    block_reason = get_account_runtime_block_reason(account)
    if block_reason:
        action = _finish_warmup_action(action, status=WarmupAction.Status.SKIPPED, error=block_reason)
        refresh_plan_status(action.plan)
        log_warmup_event(
            owner=action.owner,
            level=WarmupLog.Level.WARNING,
            plan=action.plan,
            action=action,
            account=account,
            message=_skipped_message(action, block_reason),
            metadata={**_action_context(action), "reason": block_reason},
        )
        return action

    try:
        result = run_client_operation(account, _operation_for_action(action))
        result_payload = result if isinstance(result, dict) else {"value": str(result)}
        metadata = {**action.metadata, **_action_context(action), "result": result_payload}
        action = _finish_warmup_action(action, status=WarmupAction.Status.SUCCEEDED, metadata=metadata)
        register_account_runtime_event(
            account,
            event_type=AccountHealthEvent.EventType.SUCCESS,
            metadata={"source": "warmup", "action_id": action.id, "action_type": action.action_type},
        )
        if not action.metadata.get("initial_cycle"):
            schedule_next_cycle_action(action)
        refresh_plan_status(action.plan)
        log_warmup_event(
            owner=action.owner,
            level=WarmupLog.Level.SUCCESS,
            plan=action.plan,
            action=action,
            account=account,
            message=_success_message(action, result_payload),
            metadata=metadata,
        )
    except Exception as exc:
        classified = classify_runtime_exception(exc)
        if classified is not None:
            event_type, metadata = classified
            metadata = {
                **metadata,
                "source": "warmup",
                "action_id": action.id,
                "action_type": action.action_type,
                "plan_id": action.plan_id,
            }
            register_account_runtime_event(account, event_type=event_type, metadata=metadata)
        action = _finish_warmup_action(action, status=WarmupAction.Status.FAILED, error=str(exc))
        schedule_next_cycle_action(action, after_error=True)
        refresh_plan_status(action.plan)
        log_warmup_event(
            owner=action.owner,
            level=WarmupLog.Level.ERROR,
            plan=action.plan,
            action=action,
            account=account,
            message=_failed_message(action, action.error),
            metadata={**_action_context(action), "error": action.error},
        )
    return action


def refresh_plan_status(plan: WarmupPlan) -> WarmupPlan:
    if plan.status != WarmupPlan.Status.RUNNING:
        return plan
    remaining = plan.actions.filter(status__in=[WarmupAction.Status.QUEUED, WarmupAction.Status.RUNNING]).exists()
    if not remaining:
        plan.status = WarmupPlan.Status.COMPLETED
        plan.completed_at = timezone.now()
        plan.save(update_fields=["status", "completed_at", "updated_at"])
    return plan
