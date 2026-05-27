from __future__ import annotations

import asyncio
import random
import re
import time

import requests
from asgiref.sync import sync_to_async
from celery.result import AsyncResult
from django.conf import settings
from django.db.models import Count
from django.utils import timezone
from pyrogram.errors import FloodWait, RPCError
from pyrogram.raw.functions.messages import SendReaction
from pyrogram.raw.types import ReactionEmoji

from apps.reaction_bot.models import HARDCODED_EMOJIS, AccountChannelBinding, ReactionJob, ReactionLog
from apps.realtime.logging import publish_log_event
from apps.telegram_accounts import protection
from apps.telegram_accounts.models import AccountHealthEvent, TelegramAccount
from apps.telegram_accounts.services import (
    get_account_runtime_block_reason,
    register_account_runtime_event,
    run_client_operation,
)


def log_reaction_event(
    job: ReactionJob | None,
    *,
    level: str,
    message: str,
    account: TelegramAccount | None = None,
    metadata: dict | None = None,
) -> ReactionLog:
    log = ReactionLog.objects.create(
        owner=job.owner if job else account.owner,
        job=job,
        account=account,
        level=level,
        message=message,
        metadata=metadata or {},
    )
    publish_log_event(
        {
            "level": level if level != ReactionLog.Level.SUCCESS else "success",
            "source": account.label if account else "reactions",
            "message": message,
            "metadata": {
                "module": "reaction_bot",
                "job_id": job.id if job else None,
                "account_id": account.id if account else None,
            },
        }
    )
    return log


async_log_reaction_event = sync_to_async(log_reaction_event, thread_sensitive=True)


def _random_delay(min_s: float, max_s: float) -> float:
    min_s = max(0.0, float(min_s))
    max_s = max(min_s, float(max_s))
    if max_s <= 0:
        return 0.0
    return random.uniform(min_s, max_s)


def _effective_delays(job: ReactionJob) -> tuple[float, float, float, float]:
    """Returns (reaction_min, reaction_max, entry_min, entry_max) adjusted via the
    shared ai_protection profile (speed_mode picks safe/balanced/fast). Reaction-bot
    delays are scaled-down vs. the comment-oriented profile defaults: divided by ~4
    because a reaction is a much cheaper action than a full comment, so the
    multipliers in the profile stay meaningful while the absolute numbers fit
    reaction cadence."""
    params = protection.protection_params(job)
    if params:
        mult = float(params.get("delay_multiplier", 1.0))
        # Scale the comment-oriented base ranges down by ~4× to reaction-cadence.
        cmin, cmax = params["comment_delay"]  # type: ignore[index]
        emin, emax = params["entry_delay"]  # type: ignore[index]
        return cmin / 4 * mult, cmax / 4 * mult, emin / 30 * mult, emax / 20 * mult
    return (
        job.reaction_delay_min,
        job.reaction_delay_max,
        job.entry_delay_min,
        job.entry_delay_max,
    )


def _clean_emoji(emoji: str) -> str:
    # Strip variation selector U+FE0F — Telegram rejects it with REACTION_INVALID
    return emoji.replace("️", "").strip()


def _normalize_source(raw: str) -> str:
    """Convert any channel reference to a form Pyrogram's get_chat() accepts."""
    value = str(raw or "").strip()
    if not value:
        return ""
    # numeric chat id — keep as-is
    if value.lstrip("-").isdigit():
        return int(value)
    value = re.sub(r"^https?://t\.me/", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^t\.me/", "", value, flags=re.IGNORECASE)
    value = value.lstrip("@")
    # strip query strings (e.g. ?start=...)
    value = value.split("?")[0].split("/")[0].strip()
    return value or raw


def _pick_emoji(job: ReactionJob, index: int) -> str:
    emojis = [_clean_emoji(e) for e in (job.emojis or []) if e] or [_clean_emoji(e) for e in HARDCODED_EMOJIS]
    if job.emoji_mode == ReactionJob.EmojiMode.SEQUENTIAL:
        return emojis[index % len(emojis)]
    return random.choice(emojis)


async def _send_reaction(app, chat_id: int, message_id: int, emoji: str) -> None:
    emoji = _clean_emoji(emoji)
    peer = await app.resolve_peer(chat_id)
    await app.invoke(
        SendReaction(
            peer=peer,
            msg_id=message_id,
            reaction=[ReactionEmoji(emoticon=emoji)],
        )
    )


async def _get_subscribed_sources(app, limit: int) -> list[str]:
    """Returns chat usernames/ids from account's dialogs (channels + groups)."""
    sources = []
    try:
        async for dialog in app.get_dialogs():
            chat = dialog.chat
            if chat is None:
                continue
            chat_type = str(getattr(chat, "type", "")).lower()
            if "channel" not in chat_type and "group" not in chat_type and "supergroup" not in chat_type:
                continue
            username = getattr(chat, "username", None)
            if username:
                sources.append(f"@{username}")
            else:
                chat_id = getattr(chat, "id", None)
                if chat_id:
                    sources.append(str(chat_id))
            if len(sources) >= limit:
                break
    except Exception:
        pass
    random.shuffle(sources)
    return sources


def _call_ai(system: str, user: str, *, max_tokens: int = 120, temperature: float = 0.7) -> str:
    """Call the configured OpenAI-compatible text provider. Returns empty string on any error."""
    base_url = getattr(settings, "PROFILE_TEXT_BASE_URL", "") or ""
    api_key = getattr(settings, "PROFILE_TEXT_API_KEY", "") or ""
    model = getattr(settings, "PROFILE_TEXT_MODEL", "gpt-4o-mini") or "gpt-4o-mini"
    if not base_url or not api_key:
        return ""
    url = base_url.rstrip("/") + "/chat/completions"
    try:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            },
            timeout=getattr(settings, "PROFILE_PROVIDER_TIMEOUT_SECONDS", 30),
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return ""


async_call_ai = sync_to_async(_call_ai, thread_sensitive=False)


async def _ai_pick_emoji(post_text: str, available_emojis: list[str]) -> str | None:
    """Ask AI to pick the single best reaction emoji for a post. Returns None if unavailable."""
    if not post_text or not post_text.strip():
        return None
    emoji_list = ", ".join(available_emojis)
    system = (
        "You are a Telegram reaction picker. "
        "Given a post text, return ONLY the single most fitting reaction emoji from the provided list. "
        "No explanation, no punctuation — just the emoji character."
    )
    user = f"Available reactions: {emoji_list}\n\nPost:\n{post_text[:600]}"
    result = await async_call_ai(system, user, max_tokens=5, temperature=0.3)
    # Extract first emoji-like character from result
    for emoji in available_emojis:
        if emoji in result:
            return emoji
    return None


async def _react_to_comments_on_post(
    app,
    job: ReactionJob,
    account: TelegramAccount,
    channel_id: int,
    message,
    available_emojis: list[str],
    emoji_index: list[int],
    reaction_counter: list[int],
    reaction_min: float,
    reaction_max: float,
) -> int:
    """React to individual comments in the discussion group for a post."""
    try:
        chat_full = await app.get_chat(channel_id)
        linked_chat = getattr(chat_full, "linked_chat", None)
    except Exception:
        return 0
    if linked_chat is None:
        return 0

    post_text = (getattr(message, "text", "") or getattr(message, "caption", "") or "").strip()
    reacted = 0

    try:
        async for comment in app.get_discussion_replies(channel_id, message.id, limit=20):
            if job.max_reactions and reaction_counter[0] >= job.max_reactions:
                break
            sender = getattr(comment, "from_user", None)
            if sender is None or getattr(sender, "is_bot", False):
                continue
            if random.random() > job.comment_reaction_probability:
                continue

            comment_text = (getattr(comment, "text", "") or getattr(comment, "caption", "") or "").strip()

            if job.ai_smart_emoji and (comment_text or post_text):
                ai_emoji = await _ai_pick_emoji(comment_text or post_text, available_emojis)
                emoji = ai_emoji if ai_emoji else _pick_emoji(job, emoji_index[0])
            else:
                emoji = _pick_emoji(job, emoji_index[0])
            emoji_index[0] += 1

            try:
                await _send_reaction(app, linked_chat.id, comment.id, emoji)
                reacted += 1
                reaction_counter[0] += 1
                await sync_to_async(ReactionJob.objects.filter(pk=job.pk).update)(reactions_sent=reaction_counter[0])
            except FloodWait:
                raise
            except Exception:
                pass

            delay = _random_delay(reaction_min, reaction_max)
            if delay:
                await asyncio.sleep(delay)
    except FloodWait:
        raise
    except Exception:
        pass

    return reacted


async def _react_in_channel(
    app,
    job: ReactionJob,
    account: TelegramAccount,
    source: str,
    reaction_counter: list[int],
    emoji_index: list[int],
    delays: tuple[float, float, float, float],
) -> int:
    reaction_min, reaction_max, _, _ = delays
    reacted = 0

    try:
        chat = await app.get_chat(_normalize_source(source))
    except Exception as exc:
        await async_log_reaction_event(
            job, level=ReactionLog.Level.ERROR, account=account,
            message=f"{account.label}: не вдалося отримати канал {source}: {exc}",
            metadata={"source": source},
        )
        return 0

    await async_log_reaction_event(
        job, level=ReactionLog.Level.INFO, account=account,
        message=f"{account.label}: реакції в {getattr(chat, 'title', source) or source}",
        metadata={"source": source},
    )

    limit = job.post_limit or 20
    chat_title = getattr(chat, "title", source) or source
    available_emojis = [_clean_emoji(e) for e in (job.emojis or []) if e] or [_clean_emoji(e) for e in HARDCODED_EMOJIS]

    try:
        async for message in app.get_chat_history(chat.id, limit=limit):
            job_fresh = await sync_to_async(ReactionJob.objects.get)(pk=job.pk)
            if job_fresh.status != ReactionJob.Status.RUNNING:
                break
            if job.max_reactions and reaction_counter[0] >= job.max_reactions:
                break
            if random.random() > job.reaction_probability:
                continue

            post_text = (getattr(message, "text", "") or getattr(message, "caption", "") or "").strip()

            # AI emoji selection
            if job.ai_smart_emoji and post_text:
                ai_emoji = await _ai_pick_emoji(post_text, available_emojis)
                emoji = ai_emoji if ai_emoji else _pick_emoji(job, emoji_index[0])
            else:
                emoji = _pick_emoji(job, emoji_index[0])
            emoji_index[0] += 1

            try:
                await _send_reaction(app, chat.id, message.id, emoji)
                reacted += 1
                reaction_counter[0] += 1
                await async_log_reaction_event(
                    job, level=ReactionLog.Level.SUCCESS, account=account,
                    message=f"{account.label}: {emoji} → {chat_title} #{message.id}",
                    metadata={"source": source, "message_id": message.id, "emoji": emoji},
                )
                await sync_to_async(ReactionJob.objects.filter(pk=job.pk).update)(reactions_sent=reaction_counter[0])
            except FloodWait:
                raise
            except Exception as exc:
                exc_str = str(exc)
                if "REACTION_INVALID" not in exc_str and "REACTIONS_TOO_MANY" not in exc_str:
                    await async_log_reaction_event(
                        job, level=ReactionLog.Level.WARNING, account=account,
                        message=f"{account.label}: реакція не відправлена #{message.id}: {exc}",
                        metadata={"source": source, "message_id": message.id},
                    )

            # React to commenters in discussion group
            if job.react_to_comments:
                comment_reacted = await _react_to_comments_on_post(
                    app, job, account, chat.id, message,
                    available_emojis, emoji_index, reaction_counter,
                    reaction_min, reaction_max,
                )
                if comment_reacted:
                    await async_log_reaction_event(
                        job, level=ReactionLog.Level.INFO, account=account,
                        message=f"{account.label}: реакції на {comment_reacted} коментарів у {chat_title} #{message.id}",
                        metadata={"source": source, "message_id": message.id, "comments_reacted": comment_reacted},
                    )

            delay = _random_delay(reaction_min, reaction_max)
            if delay:
                await asyncio.sleep(delay)
    except FloodWait:
        raise
    except Exception as exc:
        await async_log_reaction_event(
            job, level=ReactionLog.Level.ERROR, account=account,
            message=f"{account.label}: помилка в {source}: {exc}",
        )

    return reacted


async def _monitor_channel(
    app,
    job: ReactionJob,
    account: TelegramAccount,
    source: str,
    reaction_counter: list[int],
    emoji_index: list[int],
    delays: tuple[float, float, float, float],
    deadline: float,
) -> int:
    reaction_min, reaction_max, _, _ = delays
    reacted = 0
    seen_ids: set[int] = set()

    try:
        chat = await app.get_chat(_normalize_source(source))
    except Exception as exc:
        await async_log_reaction_event(
            job, level=ReactionLog.Level.ERROR, account=account,
            message=f"{account.label}: не вдалося отримати канал {source}: {exc}",
        )
        return 0

    await async_log_reaction_event(
        job, level=ReactionLog.Level.INFO, account=account,
        message=f"{account.label}: моніторинг {getattr(chat, 'title', source) or source}",
        metadata={"source": source},
    )

    chat_title = getattr(chat, "title", source) or source
    available_emojis = [_clean_emoji(e) for e in (job.emojis or []) if e] or [_clean_emoji(e) for e in HARDCODED_EMOJIS]

    async for message in app.get_chat_history(chat.id, limit=20):
        seen_ids.add(message.id)

    while time.monotonic() < deadline:
        job_fresh = await sync_to_async(ReactionJob.objects.get)(pk=job.pk)
        if job_fresh.status != ReactionJob.Status.RUNNING:
            break
        if job.max_reactions and reaction_counter[0] >= job.max_reactions:
            break

        try:
            async for message in app.get_chat_history(chat.id, limit=5):
                if message.id in seen_ids:
                    break
                seen_ids.add(message.id)

                if random.random() > job.reaction_probability:
                    continue

                post_text = (getattr(message, "text", "") or getattr(message, "caption", "") or "").strip()

                if job.ai_smart_emoji and post_text:
                    ai_emoji = await _ai_pick_emoji(post_text, available_emojis)
                    emoji = ai_emoji if ai_emoji else _pick_emoji(job, emoji_index[0])
                else:
                    emoji = _pick_emoji(job, emoji_index[0])
                emoji_index[0] += 1

                try:
                    await _send_reaction(app, chat.id, message.id, emoji)
                    reacted += 1
                    reaction_counter[0] += 1
                    await async_log_reaction_event(
                        job, level=ReactionLog.Level.SUCCESS, account=account,
                        message=f"{account.label}: {emoji} → {chat_title} (новий пост #{message.id})",
                        metadata={"source": source, "message_id": message.id, "emoji": emoji},
                    )
                    await sync_to_async(ReactionJob.objects.filter(pk=job.pk).update)(reactions_sent=reaction_counter[0])
                except FloodWait:
                    raise
                except Exception as exc:
                    await async_log_reaction_event(
                        job, level=ReactionLog.Level.WARNING, account=account,
                        message=f"{account.label}: реакція не відправлена #{message.id}: {exc}",
                    )

                if job.react_to_comments:
                    comment_reacted = await _react_to_comments_on_post(
                        app, job, account, chat.id, message,
                        available_emojis, emoji_index, reaction_counter,
                        reaction_min, reaction_max,
                    )
                    if comment_reacted:
                        await async_log_reaction_event(
                            job, level=ReactionLog.Level.INFO, account=account,
                            message=f"{account.label}: реакції на {comment_reacted} коментарів у {chat_title} #{message.id}",
                            metadata={"source": source, "message_id": message.id},
                        )

                delay = _random_delay(reaction_min, reaction_max)
                if delay:
                    await asyncio.sleep(delay)
        except FloodWait:
            raise
        except Exception:
            pass

        await asyncio.sleep(15)

    return reacted


async def _run_with_account(
    app,
    job: ReactionJob,
    account: TelegramAccount,
    sources: list[str],
    reaction_counter: list[int],
    emoji_index: list[int],
    delays: tuple[float, float, float, float],
    deadline: float | None,
) -> int:
    _, _, entry_min, entry_max = delays
    entry_delay = _random_delay(entry_min, entry_max)
    if entry_delay:
        await asyncio.sleep(entry_delay)

    effective_sources = list(sources)
    if job.use_subscriptions:
        sub_sources = await _get_subscribed_sources(app, job.subscriptions_limit or 50)
        if sub_sources:
            await async_log_reaction_event(
                job, level=ReactionLog.Level.INFO, account=account,
                message=f"{account.label}: знайдено {len(sub_sources)} каналів/груп із підписок",
            )
        effective_sources = effective_sources + sub_sources

    total = 0
    for source in effective_sources:
        job_fresh = await sync_to_async(ReactionJob.objects.get)(pk=job.pk)
        if job_fresh.status != ReactionJob.Status.RUNNING:
            break
        if job.max_reactions and reaction_counter[0] >= job.max_reactions:
            break

        if job.work_mode == ReactionJob.WorkMode.MONITORING and deadline:
            total += await _monitor_channel(app, job, account, source, reaction_counter, emoji_index, delays, deadline)
        else:
            total += await _react_in_channel(app, job, account, source, reaction_counter, emoji_index, delays)

    return total


def start_reaction_job(job: ReactionJob) -> ReactionJob:
    from apps.reaction_bot.tasks import run_reaction_job_task

    if job.status == ReactionJob.Status.RUNNING:
        return job
    job.status = ReactionJob.Status.RUNNING
    job.error = ""
    job.reactions_sent = 0
    job.started_at = timezone.now()
    job.finished_at = None
    job.save(update_fields=["status", "error", "reactions_sent", "started_at", "finished_at", "updated_at"])
    task = run_reaction_job_task.delay(job.id)
    job.celery_task_id = task.id
    job.save(update_fields=["celery_task_id", "updated_at"])
    log_reaction_event(job, level=ReactionLog.Level.INFO, message="Запуск модуля Масові реакції")
    return job


def stop_reaction_job(job: ReactionJob) -> ReactionJob:
    if job.celery_task_id:
        AsyncResult(job.celery_task_id).revoke(terminate=False)
    job.status = ReactionJob.Status.STOPPED
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "finished_at", "updated_at"])
    log_reaction_event(job, level=ReactionLog.Level.SUCCESS, message="Задачу зупинено")
    return job


def run_reaction_job(job_id: int) -> ReactionJob:
    job = ReactionJob.objects.prefetch_related("accounts", "channel_bindings").get(pk=job_id)
    accounts = list(job.accounts.filter(is_attached=True, auth_state=TelegramAccount.AuthState.CONNECTED))
    if not accounts:
        raise RuntimeError("Немає валідних акаунтів для реакцій.")

    sources = [str(s).strip() for s in (job.sources or []) if str(s).strip()]
    if not sources:
        raise RuntimeError("Немає джерел (каналів) для реакцій.")

    delays = _effective_delays(job)
    reaction_counter: list[int] = [0]
    emoji_index: list[int] = [0]
    deadline: float | None = (
        time.monotonic() + job.duration_minutes * 60
        if job.work_mode == ReactionJob.WorkMode.MONITORING and job.duration_minutes
        else None
    )

    try:
        if job.account_rotation:
            account_iter = iter(accounts * max(1, len(sources) // max(len(accounts), 1) + 1))
        else:
            account_iter = iter(accounts)

        for i, source in enumerate(sources):
            if job.max_reactions and reaction_counter[0] >= job.max_reactions:
                break
            job_fresh = ReactionJob.objects.get(pk=job.pk)
            if job_fresh.status != ReactionJob.Status.RUNNING:
                break

            account = accounts[i % len(accounts)] if job.account_rotation else accounts[0]

            block_reason = get_account_runtime_block_reason(account)
            if block_reason:
                log_reaction_event(
                    job, level=ReactionLog.Level.WARNING, account=account,
                    message=f"{account.label}: акаунт пропущено: {block_reason}",
                )
                continue

            try:
                run_client_operation(
                    account,
                    lambda app: _run_with_account(app, job, account, [source], reaction_counter, emoji_index, delays, deadline),
                )
            except FloodWait as exc:
                register_account_runtime_event(
                    account=account,
                    event_type=AccountHealthEvent.EventType.FLOOD_WAIT,
                    metadata={"job_id": job.id, "seconds": getattr(exc, "value", None)},
                )
                log_reaction_event(
                    job, level=ReactionLog.Level.ERROR, account=account,
                    message=f"{account.label}: FloodWait, акаунт відправлено в карантин",
                )
            except RPCError as exc:
                log_reaction_event(
                    job, level=ReactionLog.Level.ERROR, account=account,
                    message=f"{account.label}: Telegram error: {exc}",
                )

        job.refresh_from_db()
        if job.status == ReactionJob.Status.RUNNING:
            job.status = ReactionJob.Status.SUCCEEDED
            job.finished_at = timezone.now()
            job.error = ""
            job.save(update_fields=["status", "finished_at", "error", "updated_at"])
            log_reaction_event(
                job, level=ReactionLog.Level.SUCCESS,
                message=f"Готово. Відправлено реакцій: {reaction_counter[0]}",
            )
    except Exception as exc:
        job.status = ReactionJob.Status.FAILED
        job.error = str(exc)
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error", "finished_at", "updated_at"])
        log_reaction_event(job, level=ReactionLog.Level.ERROR, message=f"Помилка: {exc}")

    return job


def _reaction_stats(owner, *, window_hours: int = 24) -> dict:
    """Aggregates over the last `window_hours` of ReactionLog for the owner."""
    from datetime import timedelta
    from django.db.models import Q

    since = timezone.now() - timedelta(hours=window_hours)
    base = ReactionLog.objects.filter(owner=owner, created_at__gte=since)

    level_buckets = base.values("level").annotate(n=Count("id")).order_by()
    by_level = {row["level"]: row["n"] for row in level_buckets}

    by_account = list(
        base.filter(level=ReactionLog.Level.SUCCESS, account__isnull=False)
        .values("account_id", "account__label")
        .annotate(
            reactions=Count("id"),
            warnings=Count("id", filter=Q(level=ReactionLog.Level.WARNING)),
        )
        .order_by("-reactions")[:20]
    )

    top_errors = list(
        base.filter(level__in=[ReactionLog.Level.ERROR, ReactionLog.Level.WARNING])
        .values("message")
        .annotate(n=Count("id"))
        .order_by("-n")[:10]
    )

    return {
        "window_hours": window_hours,
        "total_events": base.count(),
        "successes": int(by_level.get(ReactionLog.Level.SUCCESS, 0)),
        "warnings": int(by_level.get(ReactionLog.Level.WARNING, 0)),
        "errors": int(by_level.get(ReactionLog.Level.ERROR, 0)),
        "infos": int(by_level.get(ReactionLog.Level.INFO, 0)),
        "by_account": by_account,
        "top_errors": top_errors,
    }


def overview_payload(owner) -> dict:
    jobs = (
        ReactionJob.objects.filter(owner=owner)
        .annotate(log_count=Count("logs", distinct=True))
        .prefetch_related("accounts")
        .order_by("-created_at")[:20]
    )
    latest_job = jobs[0] if jobs else None
    accounts = TelegramAccount.objects.filter(
        owner=owner, is_attached=True, auth_state=TelegramAccount.AuthState.CONNECTED
    ).select_related("proxy", "role_template")
    bindings = AccountChannelBinding.objects.filter(owner=owner).select_related("account")
    from apps.channel_parser.models import ChannelCollectionTemplate
    channel_templates = list(
        ChannelCollectionTemplate.objects.filter(owner=owner)
        .annotate(item_count=Count("items", distinct=True))
        .prefetch_related("items")
        .order_by("name", "-created_at")
    )
    return {
        "jobs": jobs,
        "logs": (
            ReactionLog.objects.filter(owner=owner, job=latest_job).select_related("account").order_by("created_at")[:500]
            if latest_job else []
        ),
        "accounts": accounts,
        "bindings": bindings,
        "channel_templates": channel_templates,
        "hardcoded_emojis": HARDCODED_EMOJIS,
        "stats": _reaction_stats(owner),
    }
