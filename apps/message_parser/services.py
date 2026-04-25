from __future__ import annotations

import asyncio
import csv
import io
import json
import random
import re
import time
from dataclasses import dataclass
from datetime import timedelta

from asgiref.sync import sync_to_async
from celery.result import AsyncResult
from django.db.models import Count
from django.utils import timezone
from pyrogram.errors import FloodWait, RPCError

from apps.channel_parser.models import ChannelCollectionTemplate
from apps.message_parser.models import MessageParserJob, MessageParserLog, ParsedUser
from apps.realtime.logging import publish_log_event
from apps.telegram_accounts.models import AccountHealthEvent, TelegramAccount
from apps.telegram_accounts.services import get_account_runtime_block_reason, register_account_runtime_event, run_client_operation


@dataclass(frozen=True)
class ParserTiming:
    request_delay_range: tuple[float, float]
    source_delay_range: tuple[float, float]
    progress_step: int


def _random_delay(delay_range: tuple[float, float]) -> float:
    lower, upper = delay_range
    lower = max(0.0, float(lower))
    upper = max(lower, float(upper))
    if upper <= 0:
        return 0.0
    if lower == upper:
        return lower
    return random.uniform(lower, upper)


def parser_timing(job: MessageParserJob) -> ParserTiming:
    if job.ai_protection:
        if job.speed_mode == MessageParserJob.SpeedMode.FAST:
            return ParserTiming(request_delay_range=(3.0, 14.0), source_delay_range=(3.0, 14.0), progress_step=250)
        if job.speed_mode == MessageParserJob.SpeedMode.SAFE:
            return ParserTiming(request_delay_range=(12.0, 60.0), source_delay_range=(12.0, 60.0), progress_step=150)
        return ParserTiming(request_delay_range=(7.0, 42.0), source_delay_range=(7.0, 42.0), progress_step=200)
    if job.fast_mode or job.speed_mode == MessageParserJob.SpeedMode.FAST:
        return ParserTiming(request_delay_range=(0.5, 1.5), source_delay_range=(0.5, 1.0), progress_step=500)
    if job.speed_mode == MessageParserJob.SpeedMode.SAFE:
        return ParserTiming(request_delay_range=(2.0, 5.0), source_delay_range=(1.5, 3.0), progress_step=300)
    return ParserTiming(request_delay_range=(1.0, 3.0), source_delay_range=(1.0, 2.0), progress_step=400)


def log_parser_event(
    job: MessageParserJob | None,
    *,
    level: str,
    message: str,
    account: TelegramAccount | None = None,
    metadata: dict[str, object] | None = None,
) -> MessageParserLog:
    log = MessageParserLog.objects.create(
        owner=job.owner if job else account.owner,
        job=job,
        account=account,
        level=level,
        message=message,
        metadata=metadata or {},
    )
    publish_log_event(
        {
            "level": level if level != MessageParserLog.Level.SUCCESS else "success",
            "source": account.label if account else "parser",
            "message": message,
            "metadata": {
                "module": "message_parser",
                "job_id": job.id if job else None,
                "account_id": account.id if account else None,
            },
        }
    )
    return log


async_log_parser_event = sync_to_async(log_parser_event, thread_sensitive=True)


def _safe_attr_text(obj, attr: str, *, limit: int | None = None) -> str:
    try:
        value = getattr(obj, attr, "")
    except Exception:
        return ""
    try:
        text = value if isinstance(value, str) else str(value or "")
    except Exception:
        return ""
    return text[:limit] if limit else text


def _normalize_source(raw: str) -> str:
    value = str(raw or "").strip()
    if not value:
        return ""
    value = re.sub(r"^https?://t\.me/", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^t\.me/", "", value, flags=re.IGNORECASE)
    value = value.lstrip("@")
    return value


def _source_variants(raw: str) -> list[object]:
    value = _normalize_source(raw)
    if not value:
        return []
    if re.fullmatch(r"-?\d+", value):
        return [int(value)]
    return [value]


def _profile_url(username: str) -> str:
    username = (username or "").strip().lstrip("@")
    return f"https://t.me/{username}" if username else ""


def _matches_keywords(text: str, keywords: list[str]) -> list[str]:
    haystack = " ".join((text or "").lower().split())
    if not haystack:
        return []
    matched = []
    for keyword in keywords or []:
        needle = " ".join(str(keyword or "").lower().split())
        if needle and needle in haystack:
            matched.append(keyword)
    return matched


def _message_text(message) -> str:
    return (
        _safe_attr_text(message, "text", limit=4000)
        or _safe_attr_text(message, "caption", limit=4000)
        or ""
    )


def _message_date(message):
    value = getattr(message, "date", None)
    if not value:
        return None
    return timezone.make_aware(value) if timezone.is_naive(value) else value


def _candidate_users_from_message(message, *, include_forwards: bool, include_replies: bool):
    yielded = []
    user = getattr(message, "from_user", None)
    if user is not None:
        yielded.append(("author", user))
    if include_forwards:
        forwarded = getattr(message, "forward_from", None)
        if forwarded is not None:
            yielded.append(("forwarded", forwarded))
    if include_replies:
        replied = getattr(getattr(message, "reply_to_message", None), "from_user", None)
        if replied is not None:
            yielded.append(("reply", replied))
    return yielded


def _passes_user_filters(job: MessageParserJob, user) -> bool:
    username = _safe_attr_text(user, "username", limit=255)
    has_photo = bool(getattr(user, "photo", None))
    if job.skip_bots and bool(getattr(user, "is_bot", False)):
        return False
    if job.skip_deleted and (bool(getattr(user, "is_deleted", False)) or not (getattr(user, "id", None) or username)):
        return False
    if job.skip_scam and (bool(getattr(user, "is_scam", False)) or bool(getattr(user, "is_fake", False))):
        return False
    if job.only_with_username and not username:
        return False
    if job.only_with_photo and not has_photo:
        return False
    if job.only_premium and not bool(getattr(user, "is_premium", False)):
        return False
    return True


def _user_key(user) -> str:
    user_id = getattr(user, "id", None)
    username = _safe_attr_text(user, "username", limit=255).lower()
    return f"id:{user_id}" if user_id is not None else f"username:{username}"


def _build_result_record(*, job: MessageParserJob, source_chat, source_ref: str, user, stats: dict[str, object]) -> dict[str, object]:
    username = _safe_attr_text(user, "username", limit=255)
    full_name = " ".join(
        part for part in (_safe_attr_text(user, "first_name", limit=255), _safe_attr_text(user, "last_name", limit=255)) if part
    ).strip()
    return {
        "owner_id": job.owner_id,
        "job_id": job.id,
        "source_ref": source_ref[:255],
        "source_title": (_safe_attr_text(source_chat, "title", limit=255) or _safe_attr_text(source_chat, "first_name", limit=255))[:255],
        "source_username": _safe_attr_text(source_chat, "username", limit=255),
        "source_url": _profile_url(_safe_attr_text(source_chat, "username", limit=255)),
        "telegram_user_id": getattr(user, "id", None),
        "username": username,
        "full_name": (full_name or username or str(getattr(user, "id", "") or ""))[:255],
        "profile_url": _profile_url(username),
        "is_bot": bool(getattr(user, "is_bot", False)),
        "is_deleted": bool(getattr(user, "is_deleted", False)),
        "is_scam": bool(getattr(user, "is_scam", False) or getattr(user, "is_fake", False)),
        "is_premium": bool(getattr(user, "is_premium", False)),
        "has_photo": bool(getattr(user, "photo", None)),
        "message_count": int(stats["message_count"]),
        "first_message_at": stats["first_message_at"],
        "last_message_at": stats["last_message_at"],
        "matched_keywords": sorted(stats["matched_keywords"]),
        "sample_message": str(stats["sample_message"])[:2000],
        "metadata": {
            "roles": sorted(stats["roles"]),
            "source_chat_id": getattr(source_chat, "id", None),
        },
    }


def _bulk_replace_results(job_id: int, rows: list[dict[str, object]]) -> None:
    ParsedUser.objects.filter(job_id=job_id).delete()
    deduped = {}
    for row in rows:
        key = (
            row.get("source_ref") or "",
            row.get("telegram_user_id"),
            (row.get("username") or "").lower(),
        )
        existing = deduped.get(key)
        if existing is None or int(row.get("message_count") or 0) > int(existing.get("message_count") or 0):
            deduped[key] = row
    ParsedUser.objects.bulk_create([ParsedUser(**row) for row in deduped.values()], batch_size=500)


async_bulk_replace_results = sync_to_async(_bulk_replace_results, thread_sensitive=True)


async def _parse_source(app, job: MessageParserJob, account: TelegramAccount, source_ref: str, timing: ParserTiming) -> tuple[int, str]:
    source_chat = None
    last_error = None
    for variant in _source_variants(source_ref):
        try:
            source_chat = await app.get_chat(variant)
            break
        except Exception as exc:
            last_error = exc
    if source_chat is None:
        raise RuntimeError(str(last_error or "chat not found"))

    await async_log_parser_event(
        job,
        level=MessageParserLog.Level.INFO,
        account=account,
        message=f"{account.label}: початок чату {_safe_attr_text(source_chat, 'title', limit=255) or source_ref}",
        metadata={"source": source_ref},
    )

    min_date = timezone.now() - timedelta(days=job.days_limit) if job.days_limit else None
    keywords = [item for item in (job.keywords or []) if str(item).strip()]
    scanned = 0
    users: dict[str, tuple[object, dict[str, object]]] = {}

    async for message in app.get_chat_history(source_chat.id, limit=job.message_limit):
        scanned += 1
        message_date = _message_date(message)
        if min_date and message_date and message_date < min_date:
            continue
        text = _message_text(message)
        matched_keywords = _matches_keywords(text, keywords)
        if keywords and not matched_keywords:
            continue
        for role, user in _candidate_users_from_message(
            message,
            include_forwards=job.include_forwards,
            include_replies=job.include_replies,
        ):
            if user is None or not _passes_user_filters(job, user):
                continue
            key = _user_key(user)
            current_user, stats = users.get(
                key,
                (
                    user,
                    {
                        "message_count": 0,
                        "first_message_at": message_date,
                        "last_message_at": message_date,
                        "matched_keywords": set(),
                        "sample_message": text[:500],
                        "roles": set(),
                    },
                ),
            )
            stats["message_count"] += 1
            if message_date and (stats["first_message_at"] is None or message_date < stats["first_message_at"]):
                stats["first_message_at"] = message_date
            if message_date and (stats["last_message_at"] is None or message_date > stats["last_message_at"]):
                stats["last_message_at"] = message_date
            stats["matched_keywords"].update(matched_keywords)
            if text and not stats["sample_message"]:
                stats["sample_message"] = text[:500]
            stats["roles"].add(role)
            users[key] = (current_user, stats)
        if scanned % timing.progress_step == 0:
            await async_log_parser_event(
                job,
                level=MessageParserLog.Level.INFO,
                account=account,
                message=f"{account.label}: {source_ref} перевірено повідомлень {scanned}, знайдено юзерів {len(users)}",
                metadata={"source": source_ref, "scanned": scanned, "found": len(users)},
            )

    rows = []
    for user, stats in users.values():
        if job.only_active_users and int(stats["message_count"]) < 2:
            continue
        rows.append(_build_result_record(job=job, source_chat=source_chat, source_ref=source_ref, user=user, stats=stats))

    return scanned, rows, (_safe_attr_text(source_chat, "title", limit=255) or source_ref)


async def _parse_with_account(app, job: MessageParserJob, account: TelegramAccount, timing: ParserTiming) -> tuple[int, list[dict[str, object]]]:
    total_found = 0
    total_rows: list[dict[str, object]] = []
    await async_log_parser_event(
        job,
        level=MessageParserLog.Level.INFO,
        account=account,
        message=f"{account.label}: парсинг користувачів із {len(job.sources or [])} чатів",
    )
    if job.ai_protection:
        await async_log_parser_event(
            job,
            level=MessageParserLog.Level.INFO,
            account=account,
            message=f"{account.label}: ІІ захист включено • рівень {job.speed_mode}",
        )
    for index, source_ref in enumerate(job.sources or [], start=1):
        try:
            scanned, rows, source_title = await _parse_source(app, job, account, source_ref, timing)
        except FloodWait:
            raise
        except Exception as exc:
            await async_log_parser_event(
                job,
                level=MessageParserLog.Level.WARNING,
                account=account,
                message=f"{account.label}: пропущено чат {source_ref}: {exc}",
                metadata={"source": source_ref},
            )
            continue
        total_rows.extend(rows)
        total_found += len(rows)
        await async_log_parser_event(
            job,
            level=MessageParserLog.Level.SUCCESS,
            account=account,
            message=f"{account.label}: [{index}/{len(job.sources or [])}] {source_title}: знайдено {len(rows)} користувачів",
            metadata={"source": source_ref, "found": len(rows), "scanned": scanned},
        )
        source_delay = _random_delay(timing.source_delay_range)
        if source_delay:
            await asyncio.sleep(source_delay)
    return total_found, total_rows


def start_parser_job(job: MessageParserJob) -> MessageParserJob:
    from apps.message_parser.tasks import run_message_parser_job_task

    if job.status == MessageParserJob.Status.RUNNING:
        return job
    job.status = MessageParserJob.Status.RUNNING
    job.error = ""
    job.started_at = timezone.now()
    job.finished_at = None
    job.save(update_fields=["status", "error", "started_at", "finished_at", "updated_at"])
    task = run_message_parser_job_task.delay(job.id)
    job.celery_task_id = task.id
    job.save(update_fields=["celery_task_id", "updated_at"])
    log_parser_event(job, level=MessageParserLog.Level.INFO, message="Запуск модуля Парсер по повідомленнях")
    return job


def stop_parser_job(job: MessageParserJob) -> MessageParserJob:
    if job.celery_task_id:
        AsyncResult(job.celery_task_id).revoke(terminate=False)
    job.status = MessageParserJob.Status.STOPPED
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "finished_at", "updated_at"])
    log_parser_event(job, level=MessageParserLog.Level.SUCCESS, message="Задачу зупинено")
    return job


def run_parser_job(job_id: int) -> MessageParserJob:
    job = MessageParserJob.objects.prefetch_related("accounts").get(pk=job_id)
    accounts = list(job.accounts.filter(is_attached=True, auth_state=TelegramAccount.AuthState.CONNECTED))
    if not accounts:
        raise RuntimeError("Немає валідних акаунтів для парсингу.")
    if not job.sources:
        raise RuntimeError("Немає джерел для парсингу.")

    timing = parser_timing(job)
    try:
        found_total = 0
        all_rows: list[dict[str, object]] = []
        for account in accounts:
            block_reason = get_account_runtime_block_reason(account)
            if block_reason:
                log_parser_event(job, level=MessageParserLog.Level.WARNING, account=account, message=f"{account.label}: акаунт пропущено: {block_reason}")
                continue
            try:
                found, rows = run_client_operation(account, lambda app: _parse_with_account(app, job, account, timing))
                found_total += found
                all_rows.extend(rows)
            except FloodWait as exc:
                register_account_runtime_event(
                    account=account,
                    event_type=AccountHealthEvent.EventType.FLOOD_WAIT,
                    metadata={"job_id": job.id, "seconds": getattr(exc, "value", None)},
                )
                log_parser_event(job, level=MessageParserLog.Level.ERROR, account=account, message=f"{account.label}: FloodWait, акаунт відправлено в карантин")
            except RPCError as exc:
                log_parser_event(job, level=MessageParserLog.Level.ERROR, account=account, message=f"{account.label}: Telegram error: {exc}")
            request_delay = _random_delay(timing.request_delay_range)
            if request_delay:
                time.sleep(request_delay)
        _bulk_replace_results(job.id, all_rows)
        job.status = MessageParserJob.Status.SUCCEEDED
        job.finished_at = timezone.now()
        job.error = ""
        job.save(update_fields=["status", "finished_at", "error", "updated_at"])
        log_parser_event(job, level=MessageParserLog.Level.SUCCESS, message=f"Парсинг завершено. Знайдено {ParsedUser.objects.filter(job=job).count()} користувачів")
    except Exception as exc:
        job.status = MessageParserJob.Status.FAILED
        job.error = str(exc)
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error", "finished_at", "updated_at"])
        log_parser_event(job, level=MessageParserLog.Level.ERROR, message=f"Помилка парсингу: {exc}")
    return job


def export_results(job: MessageParserJob, *, export_format: str = "csv") -> tuple[str, str, str]:
    results = job.results.order_by("-message_count", "-last_message_at", "full_name")
    export_format = (export_format or "csv").lower()
    filename = f"message-parser-{job.id}.{export_format}"
    if export_format == "txt":
        payload = []
        for result in results:
            line = result.profile_url or (f"@{result.username}" if result.username else str(result.telegram_user_id or ""))
            if line:
                payload.append(line)
        return filename, "text/plain", "\n".join(payload)
    if export_format == "json":
        payload = [
            {
                "full_name": result.full_name,
                "username": result.username,
                "profile_url": result.profile_url,
                "source_title": result.source_title,
                "message_count": result.message_count,
                "matched_keywords": result.matched_keywords,
                "last_message_at": result.last_message_at.isoformat() if result.last_message_at else None,
            }
            for result in results
        ]
        return filename, "application/json", json.dumps(payload, ensure_ascii=False, indent=2)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["full_name", "username", "profile_url", "source_title", "message_count", "matched_keywords", "last_message_at"])
    for result in results:
        writer.writerow(
            [
                result.full_name,
                result.username,
                result.profile_url,
                result.source_title,
                result.message_count,
                ", ".join(result.matched_keywords or []),
                result.last_message_at.isoformat() if result.last_message_at else "",
            ]
        )
    return filename, "text/csv", output.getvalue()


def overview_payload(owner) -> dict[str, object]:
    jobs = (
        MessageParserJob.objects.filter(owner=owner)
        .annotate(result_count=Count("results", distinct=True), log_count=Count("logs", distinct=True))
        .prefetch_related("accounts")
        .order_by("-created_at")[:20]
    )
    latest_job = jobs[0] if jobs else None
    channel_templates = list(
        ChannelCollectionTemplate.objects.filter(owner=owner)
        .annotate(item_count=Count("items", distinct=True))
        .prefetch_related("items")
        .order_by("name", "-created_at")[:100]
    )
    return {
        "jobs": jobs,
        "results": ParsedUser.objects.filter(owner=owner, job=latest_job).order_by("-message_count", "-last_message_at", "full_name")[:500] if latest_job else [],
        "logs": MessageParserLog.objects.filter(owner=owner, job=latest_job).select_related("account").order_by("created_at")[:500] if latest_job else [],
        "accounts": TelegramAccount.objects.filter(owner=owner, is_attached=True, auth_state=TelegramAccount.AuthState.CONNECTED).select_related("proxy", "role_template"),
        "channel_templates": channel_templates,
        "templates": {
            "sales": ["товарка", "дропшипінг", "маркетплейс"],
            "crypto": ["крипта", "криптогаманець", "airdrop"],
            "growth": ["розкрутити Telegram-канал", "ліди", "реклама"],
        },
    }
