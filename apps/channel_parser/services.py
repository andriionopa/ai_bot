from __future__ import annotations

import asyncio
import csv
import io
import json
import random
import re
from dataclasses import dataclass
from datetime import timedelta

from asgiref.sync import sync_to_async
from celery.result import AsyncResult
from django.db.models import Count
from django.utils import timezone
from pyrogram.enums import ChatType
from pyrogram.errors import FloodWait, RPCError

from apps.channel_parser.models import (
    ChannelCollectionTemplate,
    ChannelParserJob,
    ChannelParserLog,
    ChannelParserTemplate,
    ParsedChannel,
)
from apps.realtime.logging import publish_log_event
from apps.telegram_accounts.models import AccountHealthEvent, TelegramAccount
from apps.telegram_accounts.services import get_account_runtime_block_reason, register_account_runtime_event, run_client_operation


CHANNEL_TYPES = {ChatType.CHANNEL}
GROUP_TYPES = {ChatType.SUPERGROUP, ChatType.GROUP}


def _allowed_chat_types(job: ChannelParserJob) -> set[ChatType]:
    return GROUP_TYPES if job.parse_type == ChannelParserJob.ParseType.GROUPS else CHANNEL_TYPES


def _entity_type_for_chat(chat_type) -> str:
    return ParsedChannel.EntityType.GROUP if chat_type in GROUP_TYPES else ParsedChannel.EntityType.CHANNEL


@dataclass(frozen=True)
class ParserTiming:
    request_delay_range: tuple[float, float]
    channel_delay_range: tuple[float, float]
    history_limit: int
    dialogs_limit: int


def _random_delay(delay_range: tuple[float, float]) -> float:
    lower, upper = delay_range
    lower = max(0.0, float(lower))
    upper = max(lower, float(upper))
    if upper <= 0:
        return 0.0
    if lower == upper:
        return lower
    return random.uniform(lower, upper)


def parser_timing(job: ChannelParserJob) -> ParserTiming:
    if job.ai_protection:
        if job.speed_mode == ChannelParserJob.SpeedMode.FAST:
            return ParserTiming(request_delay_range=(3.0, 14.0), channel_delay_range=(3.0, 14.0), history_limit=5, dialogs_limit=180)
        if job.speed_mode == ChannelParserJob.SpeedMode.SAFE:
            return ParserTiming(request_delay_range=(12.0, 60.0), channel_delay_range=(12.0, 60.0), history_limit=8, dialogs_limit=100)
        return ParserTiming(request_delay_range=(7.0, 42.0), channel_delay_range=(7.0, 42.0), history_limit=6, dialogs_limit=140)
    if job.speed_mode == ChannelParserJob.SpeedMode.SAFE:
        return ParserTiming(request_delay_range=(3.0, 6.0), channel_delay_range=(2.0, 4.0), history_limit=8, dialogs_limit=120)
    if job.fast_mode or job.speed_mode == ChannelParserJob.SpeedMode.FAST:
        return ParserTiming(request_delay_range=(0.5, 1.5), channel_delay_range=(0.25, 0.75), history_limit=5, dialogs_limit=220)
    return ParserTiming(request_delay_range=(1.5, 4.0), channel_delay_range=(0.75, 2.0), history_limit=6, dialogs_limit=160)


def build_search_queries(job: ChannelParserJob) -> list[str]:
    keywords = [str(item).strip() for item in (job.keywords or []) if str(item).strip()]
    suffixes = [str(item).strip() for item in (job.suffixes or []) if str(item).strip()]
    queries = list(dict.fromkeys(keywords))
    for keyword in keywords:
        for suffix in suffixes:
            queries.append(f"{keyword} {suffix}")
    return list(dict.fromkeys(queries))


def log_parser_event(
    job: ChannelParserJob | None,
    *,
    level: str,
    message: str,
    account: TelegramAccount | None = None,
    metadata: dict[str, object] | None = None,
) -> ChannelParserLog:
    log = ChannelParserLog.objects.create(
        owner=job.owner if job else account.owner,
        job=job,
        account=account,
        level=level,
        message=message,
        metadata=metadata or {},
    )
    publish_log_event(
        {
            "level": level if level != ChannelParserLog.Level.SUCCESS else "success",
            "source": account.label if account else "parser",
            "message": message,
            "metadata": {
                "module": "channel_parser",
                "job_id": job.id if job else None,
                "account_id": account.id if account else None,
            },
        }
    )
    return log


async_log_parser_event = sync_to_async(log_parser_event, thread_sensitive=True)


def _job_result_count(job_id: int) -> int:
    return ParsedChannel.objects.filter(job_id=job_id).count()


async_job_result_count = sync_to_async(_job_result_count, thread_sensitive=True)


def _upsert_parsed_channel(job: ChannelParserJob, data: dict[str, object]) -> tuple[ParsedChannel, bool]:
    lookup = {"owner_id": job.owner_id}
    if data["username"]:
        lookup["username"] = data["username"]
    else:
        lookup["telegram_id"] = data["telegram_id"]
    return ParsedChannel.objects.update_or_create(
        **lookup,
        defaults={"owner_id": job.owner_id, "job_id": job.id, **data},
    )


async_upsert_parsed_channel = sync_to_async(_upsert_parsed_channel, thread_sensitive=True)


def _normalize_username(username: str) -> str:
    return (username or "").strip().lstrip("@")


def _channel_url(username: str) -> str:
    username = _normalize_username(username)
    return f"https://t.me/{username}" if username else ""


def _safe_text_value(value, *, limit: int | None = None) -> str:
    if value is None:
        return ""
    try:
        text = value if isinstance(value, str) else str(value)
    except UnicodeDecodeError:
        return ""
    except Exception:
        return ""
    if limit is not None:
        return text[:limit]
    return text


def _safe_attr_text(obj, attr: str, *, limit: int | None = None) -> str:
    try:
        value = getattr(obj, attr, "")
    except UnicodeDecodeError:
        return ""
    except Exception:
        return ""
    return _safe_text_value(value, limit=limit)


def _text_matches_query(text: str, query: str) -> bool:
    haystack = " ".join((text or "").lower().split())
    needle = " ".join((query or "").lower().split())
    if not needle:
        return False
    if needle in haystack:
        return True
    tokens = [token for token in needle.split(" ") if token]
    return bool(tokens) and all(token in haystack for token in tokens)


def _chat_matches_query(chat, query: str) -> bool:
    haystack = " ".join(
        part
        for part in (
            _safe_attr_text(chat, "title", limit=255),
            _safe_attr_text(chat, "first_name", limit=255),
            _safe_attr_text(chat, "username", limit=255),
            _safe_attr_text(chat, "description", limit=1000),
        )
        if part
    )
    return _text_matches_query(haystack, query)


def _text_language_score(text: str) -> dict[str, int]:
    lower = (text or "").lower()
    return {
        "uk": sum(lower.count(marker) for marker in (" і ", "є", "ї", "ґ", "що", "для", "україн")),
        "ru": sum(lower.count(marker) for marker in (" и ", "ы", "э", "что", "для", "бизнес", "заработ")),
        "be": sum(lower.count(marker) for marker in ("ў", "ць", "гэта", "беларус")),
        "en": len(re.findall(r"\b(the|and|for|business|earn|telegram|channel)\b", lower)),
        "tr": len(re.findall(r"\b(ve|için|kanal|para)\b", lower)),
        "es": len(re.findall(r"\b(el|la|para|negocio|dinero)\b", lower)),
        "de": len(re.findall(r"\b(der|die|das|für|geschäft)\b", lower)),
        "fr": len(re.findall(r"\b(le|la|pour|business|argent)\b", lower)),
    }


def detect_language(text: str) -> str:
    scores = _text_language_score(text)
    best, score = max(scores.items(), key=lambda item: item[1])
    if score <= 0:
        if re.search(r"[а-яіїєґ]", (text or "").lower()):
            return "ru"
        return "en" if re.search(r"[a-z]", (text or "").lower()) else ""
    return best


def rate_channel(*, subscribers: int, recent_posts: int, days_since_last_post: int | None, comments_open: bool | None) -> int:
    score = 1
    if subscribers >= 500:
        score += 1
    if subscribers >= 5_000:
        score += 1
    if subscribers >= 50_000:
        score += 1
    if recent_posts >= 3:
        score += 2
    elif recent_posts:
        score += 1
    if days_since_last_post is not None:
        if days_since_last_post <= 2:
            score += 2
        elif days_since_last_post <= 14:
            score += 1
    if comments_open:
        score += 1
    return max(1, min(10, score))


def _aware_datetime(value):
    if not value:
        return None
    return timezone.make_aware(value) if timezone.is_naive(value) else value


async def _inspect_channel(app, chat_ref, *, query: str, job: ChannelParserJob, timing: ParserTiming) -> dict[str, object] | None:
    chat = await app.get_chat(chat_ref)
    chat_type = getattr(chat, "type", None)
    if chat_type not in _allowed_chat_types(job):
        return None

    title = _safe_attr_text(chat, "title", limit=255) or _safe_attr_text(chat, "first_name", limit=255) or _safe_text_value(chat_ref, limit=255)
    username = _normalize_username(_safe_attr_text(chat, "username", limit=255) or "")
    subscribers = int(getattr(chat, "members_count", 0) or 0)
    if not subscribers:
        try:
            subscribers = int(await app.get_chat_members_count(chat.id))
        except Exception:
            subscribers = 0
    if subscribers < job.subscriber_min or subscribers > job.subscriber_max:
        return None

    messages = []
    async for message in app.get_chat_history(chat.id, limit=timing.history_limit):
        messages.append(message)

    last_post_at = None
    text_parts = [title, _safe_attr_text(chat, "description", limit=2000)]
    for message in messages:
        message_date = _aware_datetime(getattr(message, "date", None))
        if message_date and (last_post_at is None or message_date > last_post_at):
            last_post_at = message_date
        text_parts.append(_safe_attr_text(message, "text", limit=500) or _safe_attr_text(message, "caption", limit=500))

    now = timezone.now()
    days_since_last = (now - last_post_at).days if last_post_at else None
    recent_posts = sum(
        1
        for message in messages
        if (message_date := _aware_datetime(getattr(message, "date", None))) and now - message_date <= timedelta(days=14)
    )
    activity_level = "active" if days_since_last is not None and days_since_last <= 14 and recent_posts >= 2 else "inactive"
    if job.activity_filter == ChannelParserJob.ActivityFilter.ACTIVE and activity_level != "active":
        return None
    if job.activity_filter == ChannelParserJob.ActivityFilter.INACTIVE and activity_level != "inactive":
        return None

    linked_chat = getattr(chat, "linked_chat", None)
    comments_open = bool(linked_chat)
    if job.comments_filter == ChannelParserJob.CommentsFilter.OPEN and not comments_open:
        return None
    if job.comments_filter == ChannelParserJob.CommentsFilter.CLOSED and comments_open:
        return None

    text_blob = " ".join(part for part in text_parts if part)
    language = detect_language(text_blob) if job.language_detection else ""
    languages = job.languages or []
    if job.language_detection and languages and language and language not in languages:
        return None

    rating = rate_channel(
        subscribers=subscribers,
        recent_posts=recent_posts,
        days_since_last_post=days_since_last,
        comments_open=comments_open,
    )
    if rating < job.rating_min:
        return None

    return {
        "title": title[:255],
        "username": username[:255],
        "url": _channel_url(username),
        "telegram_id": getattr(chat, "id", None),
        "entity_type": _entity_type_for_chat(chat_type),
        "subscribers": subscribers,
        "rating": rating,
        "language": language,
        "activity_level": activity_level,
        "comments_open": comments_open,
        "last_post_at": last_post_at,
        "matched_query": query[:255],
        "description": _safe_attr_text(chat, "description", limit=2000),
        "metadata": {
            "recent_posts": recent_posts,
            "days_since_last_post": days_since_last,
            "linked_chat": _safe_attr_text(linked_chat, "title", limit=255) if linked_chat else "",
        },
    }


async def _iter_global_candidates(app, query: str):
    async for message in app.search_global(query=query, limit=30):
        chat = getattr(message, "chat", None)
        if not chat:
            continue
        chat_ref = getattr(chat, "username", None) or getattr(chat, "id", None)
        if chat_ref:
            yield chat_ref


async def _iter_subscription_candidates(app, query: str, timing: ParserTiming):
    async for dialog in app.get_dialogs(limit=timing.dialogs_limit):
        chat = getattr(dialog, "chat", None)
        if not chat:
            continue
        if not _chat_matches_query(chat, query):
            continue
        chat_ref = getattr(chat, "username", None) or getattr(chat, "id", None)
        if chat_ref:
            yield chat_ref


async def _subscription_refs(app, timing: ParserTiming) -> set[object]:
    refs: set[object] = set()
    if not hasattr(app, "get_dialogs"):
        return refs
    async for dialog in app.get_dialogs(limit=timing.dialogs_limit):
        chat = getattr(dialog, "chat", None)
        if not chat:
            continue
        username = getattr(chat, "username", None)
        chat_id = getattr(chat, "id", None)
        if username:
            refs.add(_normalize_username(username))
        if chat_id is not None:
            refs.add(chat_id)
    return refs


async def _parse_with_account(app, job: ChannelParserJob, account: TelegramAccount, queries: list[str], timing: ParserTiming) -> int:
    found = 0
    seen_refs = set()
    subscribed_refs = await _subscription_refs(app, timing) if job.search_scope in {ChannelParserJob.SearchScope.GLOBAL, ChannelParserJob.SearchScope.BOTH} else set()
    await async_log_parser_event(job, level=ChannelParserLog.Level.INFO, account=account, message=f"{account.label}: запуск парсингу даних")
    for query in queries:
        if await async_job_result_count(job.id) >= job.result_limit:
            break
        sources = []
        if job.search_scope in {ChannelParserJob.SearchScope.GLOBAL, ChannelParserJob.SearchScope.BOTH}:
            sources.append(("global", "Telegram global", _iter_global_candidates(app, query)))
        if job.search_scope in {ChannelParserJob.SearchScope.SUBSCRIPTIONS, ChannelParserJob.SearchScope.BOTH}:
            sources.append(("subscriptions", "підписки акаунта", _iter_subscription_candidates(app, query, timing)))

        for source_code, source_label, candidate_iter in sources:
            await async_log_parser_event(
                job,
                level=ChannelParserLog.Level.INFO,
                account=account,
                message=f"{account.label}: пошук «{query}» через {source_label}",
                metadata={"query": query, "source": source_code},
            )
            scanned = 0
            async for chat_ref in candidate_iter:
                normalized_ref = _normalize_username(chat_ref) if isinstance(chat_ref, str) else chat_ref
                if source_code == "global" and normalized_ref in subscribed_refs:
                    continue
                if chat_ref in seen_refs:
                    continue
                seen_refs.add(chat_ref)
                scanned += 1
                try:
                    data = await _inspect_channel(app, chat_ref, query=query, job=job, timing=timing)
                except FloodWait:
                    raise
                except Exception as exc:
                    await async_log_parser_event(
                        job,
                        level=ChannelParserLog.Level.WARNING,
                        account=account,
                        message=f"{account.label}: пропущено чат {chat_ref}: {exc}",
                        metadata={"chat": str(chat_ref), "query": query, "source": source_code},
                    )
                    continue
                if not data:
                    continue
                channel, created = await async_upsert_parsed_channel(job, data)
                if created:
                    found += 1
                    await async_log_parser_event(
                        job,
                        level=ChannelParserLog.Level.SUCCESS,
                        account=account,
                        message=f"Знайдено канал: {channel.title} ({channel.url or channel.telegram_id})",
                        metadata={"channel_id": channel.id, "query": query, "source": source_code},
                    )
                if await async_job_result_count(job.id) >= job.result_limit:
                    break
                channel_delay = _random_delay(timing.channel_delay_range)
                if channel_delay:
                    await asyncio.sleep(channel_delay)
            await async_log_parser_event(
                job,
                level=ChannelParserLog.Level.INFO,
                account=account,
                message=f"{account.label}: «{query}» через {source_label} перевірено {scanned} чатів",
                metadata={"query": query, "source": source_code},
            )
            if await async_job_result_count(job.id) >= job.result_limit:
                break
        request_delay = _random_delay(timing.request_delay_range)
        if request_delay:
            await asyncio.sleep(request_delay)
    return found


def start_parser_job(job: ChannelParserJob) -> ChannelParserJob:
    from apps.channel_parser.tasks import run_channel_parser_job_task

    if job.status == ChannelParserJob.Status.RUNNING:
        return job
    job.status = ChannelParserJob.Status.RUNNING
    job.error = ""
    job.started_at = timezone.now()
    job.finished_at = None
    job.save(update_fields=["status", "error", "started_at", "finished_at", "updated_at"])
    task = run_channel_parser_job_task.delay(job.id)
    job.celery_task_id = task.id
    job.save(update_fields=["celery_task_id", "updated_at"])
    log_parser_event(job, level=ChannelParserLog.Level.INFO, message="Запуск модуля Парсинг даних")
    return job


def stop_parser_job(job: ChannelParserJob) -> ChannelParserJob:
    if job.celery_task_id:
        AsyncResult(job.celery_task_id).revoke(terminate=False)
    job.status = ChannelParserJob.Status.STOPPED
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "finished_at", "updated_at"])
    log_parser_event(job, level=ChannelParserLog.Level.SUCCESS, message="Задача успішно остановлена")
    return job


def run_parser_job(job_id: int) -> ChannelParserJob:
    job = ChannelParserJob.objects.prefetch_related("accounts").get(pk=job_id)
    queries = build_search_queries(job)
    accounts = list(job.accounts.filter(is_attached=True, auth_state=TelegramAccount.AuthState.CONNECTED))
    if not queries:
        raise RuntimeError("Немає ключових слів для парсингу.")
    if not accounts:
        raise RuntimeError("Немає валідних акаунтів для парсингу.")

    timing = parser_timing(job)
    log_parser_event(job, level=ChannelParserLog.Level.INFO, message=f"Всього комбінацій: {len(queries)}")
    found_total = 0
    try:
        for account in accounts:
            block_reason = get_account_runtime_block_reason(account)
            if block_reason:
                log_parser_event(job, level=ChannelParserLog.Level.WARNING, account=account, message=f"{account.label}: акаунт пропущено: {block_reason}")
                continue
            try:
                found_total += run_client_operation(account, lambda app: _parse_with_account(app, job, account, queries, timing))
            except FloodWait as exc:
                register_account_runtime_event(
                    account=account,
                    event_type=AccountHealthEvent.EventType.FLOOD_WAIT,
                    severity=AccountHealthEvent.Severity.HIGH,
                    score_delta=-15,
                    reason=f"Parser FloodWait {getattr(exc, 'value', '')}s",
                    metadata={"job_id": job.id, "seconds": getattr(exc, "value", None)},
                )
                log_parser_event(job, level=ChannelParserLog.Level.ERROR, account=account, message=f"{account.label}: FloodWait, акаунт відправлено в карантин")
            except RPCError as exc:
                log_parser_event(job, level=ChannelParserLog.Level.ERROR, account=account, message=f"{account.label}: Telegram error: {exc}")
            if ParsedChannel.objects.filter(job=job).count() >= job.result_limit:
                break
        job.status = ChannelParserJob.Status.SUCCEEDED
        job.finished_at = timezone.now()
        job.error = ""
        job.save(update_fields=["status", "finished_at", "error", "updated_at"])
        log_parser_event(job, level=ChannelParserLog.Level.SUCCESS, message=f"Парсинг завершено: знайдено {ParsedChannel.objects.filter(job=job).count()} каналів")
    except Exception as exc:
        job.status = ChannelParserJob.Status.FAILED
        job.error = str(exc)
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error", "finished_at", "updated_at"])
        log_parser_event(job, level=ChannelParserLog.Level.ERROR, message=f"Помилка парсингу: {exc}")
    return job


def clone_last_job(owner) -> ChannelParserJob | None:
    latest = ChannelParserJob.objects.filter(owner=owner).order_by("-created_at").first()
    if not latest:
        return None
    latest.pk = None
    latest.status = ChannelParserJob.Status.DRAFT
    latest.celery_task_id = ""
    latest.error = ""
    latest.started_at = None
    latest.finished_at = None
    latest.name = f"{latest.name} copy"
    latest.save()
    return latest


def export_results(job: ChannelParserJob, *, export_format: str = "csv") -> tuple[str, str, str]:
    results = job.results.order_by("-rating", "-subscribers", "title")
    export_format = (export_format or "csv").lower()
    filename = f"channel-parser-{job.id}.{export_format}"
    if export_format == "txt":
        return filename, "text/plain", "\n".join(result.url or result.username for result in results if result.url or result.username)
    if export_format == "json":
        payload = [
            {
                "title": result.title,
                "username": result.username,
                "url": result.url,
                "subscribers": result.subscribers,
                "rating": result.rating,
                "language": result.language,
                "activity_level": result.activity_level,
                "comments_open": result.comments_open,
            }
            for result in results
        ]
        return filename, "application/json", json.dumps(payload, ensure_ascii=False, indent=2)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["title", "username", "url", "subscribers", "rating", "language", "activity", "comments_open"])
    for result in results:
        writer.writerow([result.title, result.username, result.url, result.subscribers, result.rating, result.language, result.activity_level, result.comments_open])
    return filename, "text/csv", output.getvalue()


def overview_payload(owner) -> dict[str, object]:
    jobs = (
        ChannelParserJob.objects.filter(owner=owner)
        .annotate(result_count=Count("results", distinct=True), log_count=Count("logs", distinct=True))
        .prefetch_related("accounts")
        .order_by("-created_at")[:20]
    )
    channel_templates = list(
        ChannelCollectionTemplate.objects.filter(owner=owner)
        .annotate(item_count=Count("items", distinct=True))
        .order_by("name", "-created_at")[:100]
    )
    template_ids = [template.id for template in channel_templates]
    if template_ids:
        template_items = (
            ParsedChannel.objects.none()
        )
        from apps.channel_parser.models import ChannelCollectionItem

        items = list(
            ChannelCollectionItem.objects.filter(template_id__in=template_ids)
            .order_by("title", "id")
        )
        items_by_template = {}
        for item in items:
            bucket = items_by_template.setdefault(item.template_id, [])
            if len(bucket) < 30:
                bucket.append(item)
        for template in channel_templates:
            template._prefetched_items = items_by_template.get(template.id, [])
    latest_job = jobs[0] if jobs else None
    return {
        "jobs": jobs,
        "results": ParsedChannel.objects.filter(owner=owner, job=latest_job).order_by("-rating", "-subscribers", "title")[:300] if latest_job else [],
        "logs": ChannelParserLog.objects.filter(owner=owner, job=latest_job).select_related("account").order_by("created_at")[:300] if latest_job else [],
        "accounts": TelegramAccount.objects.filter(owner=owner, is_attached=True, auth_state=TelegramAccount.AuthState.CONNECTED).select_related("proxy", "role_template"),
        "parser_templates": ChannelParserTemplate.objects.filter(owner=owner).order_by("name", "-created_at")[:100],
        "channel_templates": channel_templates,
        "templates": {
            "business": ["Бізнес", "Заробіток", "Бізнес Telegram", "Бізнес ідеї"],
            "crypto": ["Крипта", "Airdrop", "Crypto news", "Web3"],
            "ecommerce": ["Дропшипінг", "Товарка", "Маркетплейс", "Опт"],
        },
    }
