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
from apps.comment_parser.models import CommentParserJob, CommentParserLog, ParsedCommenter
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


def parser_timing(job: CommentParserJob) -> ParserTiming:
    if job.ai_protection:
        if job.speed_mode == CommentParserJob.SpeedMode.FAST:
            return ParserTiming(request_delay_range=(3.0, 14.0), source_delay_range=(3.0, 14.0), progress_step=20)
        if job.speed_mode == CommentParserJob.SpeedMode.SAFE:
            return ParserTiming(request_delay_range=(12.0, 60.0), source_delay_range=(12.0, 60.0), progress_step=10)
        return ParserTiming(request_delay_range=(7.0, 42.0), source_delay_range=(7.0, 42.0), progress_step=15)
    if job.fast_mode or job.speed_mode == CommentParserJob.SpeedMode.FAST:
        return ParserTiming(request_delay_range=(0.5, 1.5), source_delay_range=(0.5, 1.0), progress_step=50)
    if job.speed_mode == CommentParserJob.SpeedMode.SAFE:
        return ParserTiming(request_delay_range=(2.0, 5.0), source_delay_range=(1.5, 3.0), progress_step=30)
    return ParserTiming(request_delay_range=(1.0, 3.0), source_delay_range=(1.0, 2.0), progress_step=40)


def log_parser_event(
    job: CommentParserJob | None,
    *,
    level: str,
    message: str,
    account: TelegramAccount | None = None,
    metadata: dict[str, object] | None = None,
) -> CommentParserLog:
    log = CommentParserLog.objects.create(
        owner=job.owner if job else account.owner,
        job=job,
        account=account,
        level=level,
        message=message,
        metadata=metadata or {},
    )
    publish_log_event(
        {
            "level": level if level != CommentParserLog.Level.SUCCESS else "success",
            "source": account.label if account else "parser",
            "message": message,
            "metadata": {
                "module": "comment_parser",
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


def _comment_text(message) -> str:
    return (
        _safe_attr_text(message, "text", limit=4000)
        or _safe_attr_text(message, "caption", limit=4000)
        or ""
    )


def _comment_date(message):
    value = getattr(message, "date", None)
    if not value:
        return None
    return timezone.make_aware(value) if timezone.is_naive(value) else value


def _passes_user_filters(job: CommentParserJob, user) -> bool:
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


def _build_result_record(
    *, job: CommentParserJob, source_chat, source_ref: str, user, stats: dict[str, object]
) -> dict[str, object]:
    username = _safe_attr_text(user, "username", limit=255)
    full_name = " ".join(
        part
        for part in (
            _safe_attr_text(user, "first_name", limit=255),
            _safe_attr_text(user, "last_name", limit=255),
        )
        if part
    ).strip()
    return {
        "owner_id": job.owner_id,
        "job_id": job.id,
        "source_ref": source_ref[:255],
        "source_title": (
            _safe_attr_text(source_chat, "title", limit=255) or _safe_attr_text(source_chat, "first_name", limit=255)
        )[:255],
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
        "comment_count": int(stats["comment_count"]),
        "first_comment_at": stats["first_comment_at"],
        "last_comment_at": stats["last_comment_at"],
        "matched_keywords": sorted(stats["matched_keywords"]),
        "sample_comment": str(stats["sample_comment"])[:2000],
        "metadata": {
            "source_chat_id": getattr(source_chat, "id", None),
        },
    }


def _bulk_replace_results(job_id: int, rows: list[dict[str, object]]) -> None:
    ParsedCommenter.objects.filter(job_id=job_id).delete()
    deduped = {}
    for row in rows:
        key = (
            row.get("source_ref") or "",
            row.get("telegram_user_id"),
            (row.get("username") or "").lower(),
        )
        existing = deduped.get(key)
        if existing is None or int(row.get("comment_count") or 0) > int(existing.get("comment_count") or 0):
            deduped[key] = row
    ParsedCommenter.objects.bulk_create([ParsedCommenter(**row) for row in deduped.values()], batch_size=500)


async_bulk_replace_results = sync_to_async(_bulk_replace_results, thread_sensitive=True)


async def _parse_source(
    app, job: CommentParserJob, account: TelegramAccount, source_ref: str, timing: ParserTiming
) -> tuple[int, list[dict[str, object]], str]:
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

    # Коментарі в Telegram — це повідомлення у linked discussion group.
    # Якщо канал не має linked_chat — коментарі закриті.
    linked_chat = getattr(source_chat, "linked_chat", None)
    if linked_chat is None:
        raise RuntimeError(
            f"Коментарі закриті: канал «{_safe_attr_text(source_chat, 'title', limit=255) or source_ref}» "
            "не має відкритого розділу обговорень"
        )

    await async_log_parser_event(
        job,
        level=CommentParserLog.Level.INFO,
        account=account,
        message=(
            f"{account.label}: початок парсингу коментарів "
            f"{_safe_attr_text(source_chat, 'title', limit=255) or source_ref}"
        ),
        metadata={"source": source_ref},
    )

    min_date = timezone.now() - timedelta(days=job.days_limit) if job.days_limit else None
    keywords = [item for item in (job.keywords or []) if str(item).strip()]
    posts_scanned = 0
    users: dict[str, tuple[object, dict[str, object]]] = {}

    async for message in app.get_chat_history(source_chat.id, limit=job.post_limit):
        posts_scanned += 1
        post_date = _comment_date(message)
        if min_date and post_date and post_date < min_date:
            continue

        try:
            async for comment in app.get_discussion_replies(source_chat.id, message.id, limit=job.comment_limit):
                user = getattr(comment, "from_user", None)
                if user is None:
                    continue
                if not _passes_user_filters(job, user):
                    continue
                text = _comment_text(comment)
                matched_keywords = _matches_keywords(text, keywords)
                if keywords and not matched_keywords:
                    continue
                comment_date = _comment_date(comment)
                key = _user_key(user)
                current_user, stats = users.get(
                    key,
                    (
                        user,
                        {
                            "comment_count": 0,
                            "first_comment_at": comment_date,
                            "last_comment_at": comment_date,
                            "matched_keywords": set(),
                            "sample_comment": text[:500],
                        },
                    ),
                )
                stats["comment_count"] += 1
                if comment_date and (stats["first_comment_at"] is None or comment_date < stats["first_comment_at"]):
                    stats["first_comment_at"] = comment_date
                if comment_date and (stats["last_comment_at"] is None or comment_date > stats["last_comment_at"]):
                    stats["last_comment_at"] = comment_date
                stats["matched_keywords"].update(matched_keywords)
                if text and not stats["sample_comment"]:
                    stats["sample_comment"] = text[:500]
                users[key] = (current_user, stats)
        except Exception:
            # Конкретний пост може не мати обговорення — пропускаємо
            continue

        if posts_scanned % timing.progress_step == 0:
            await async_log_parser_event(
                job,
                level=CommentParserLog.Level.INFO,
                account=account,
                message=(
                    f"{account.label}: {source_ref} перевірено постів {posts_scanned}, "
                    f"знайдено коментаторів {len(users)}"
                ),
                metadata={"source": source_ref, "posts_scanned": posts_scanned, "found": len(users)},
            )

    rows = []
    for user, stats in users.values():
        if job.only_active_users and int(stats["comment_count"]) < 2:
            continue
        rows.append(
            _build_result_record(job=job, source_chat=source_chat, source_ref=source_ref, user=user, stats=stats)
        )

    source_title = _safe_attr_text(source_chat, "title", limit=255) or source_ref
    return posts_scanned, rows, source_title


async def _parse_with_account(
    app, job: CommentParserJob, account: TelegramAccount, timing: ParserTiming
) -> tuple[int, list[dict[str, object]]]:
    total_found = 0
    total_rows: list[dict[str, object]] = []
    await async_log_parser_event(
        job,
        level=CommentParserLog.Level.INFO,
        account=account,
        message=f"{account.label}: парсинг коментарів із {len(job.sources or [])} джерел",
    )
    if job.ai_protection:
        await async_log_parser_event(
            job,
            level=CommentParserLog.Level.INFO,
            account=account,
            message=f"{account.label}: ІІ захист включено • рівень {job.speed_mode}",
        )
    for index, source_ref in enumerate(job.sources or [], start=1):
        try:
            posts_scanned, rows, source_title = await _parse_source(app, job, account, source_ref, timing)
        except FloodWait:
            raise
        except Exception as exc:
            await async_log_parser_event(
                job,
                level=CommentParserLog.Level.ERROR,
                account=account,
                message=f"{account.label}: пропущено джерело {source_ref}: {exc}",
                metadata={"source": source_ref},
            )
            continue
        total_rows.extend(rows)
        total_found += len(rows)
        await async_log_parser_event(
            job,
            level=CommentParserLog.Level.SUCCESS,
            account=account,
            message=(
                f"{account.label}: [{index}/{len(job.sources or [])}] {source_title}: "
                f"знайдено {len(rows)} коментаторів із {posts_scanned} постів"
            ),
            metadata={"source": source_ref, "found": len(rows), "posts_scanned": posts_scanned},
        )
        source_delay = _random_delay(timing.source_delay_range)
        if source_delay:
            await asyncio.sleep(source_delay)
    return total_found, total_rows


def start_parser_job(job: CommentParserJob) -> CommentParserJob:
    from apps.comment_parser.tasks import run_comment_parser_job_task

    if job.status == CommentParserJob.Status.RUNNING:
        return job
    job.status = CommentParserJob.Status.RUNNING
    job.error = ""
    job.started_at = timezone.now()
    job.finished_at = None
    job.save(update_fields=["status", "error", "started_at", "finished_at", "updated_at"])
    task = run_comment_parser_job_task.delay(job.id)
    job.celery_task_id = task.id
    job.save(update_fields=["celery_task_id", "updated_at"])
    log_parser_event(job, level=CommentParserLog.Level.INFO, message="Запуск модуля Парсер по коментарях")
    return job


def stop_parser_job(job: CommentParserJob) -> CommentParserJob:
    if job.celery_task_id:
        AsyncResult(job.celery_task_id).revoke(terminate=False)
    job.status = CommentParserJob.Status.STOPPED
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "finished_at", "updated_at"])
    log_parser_event(job, level=CommentParserLog.Level.SUCCESS, message="Задачу зупинено")
    return job


def run_parser_job(job_id: int) -> CommentParserJob:
    job = CommentParserJob.objects.prefetch_related("accounts").get(pk=job_id)
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
                log_parser_event(
                    job,
                    level=CommentParserLog.Level.WARNING,
                    account=account,
                    message=f"{account.label}: акаунт пропущено: {block_reason}",
                )
                continue
            try:
                found, rows = run_client_operation(account, lambda app: _parse_with_account(app, job, account, timing))
                found_total += found
                all_rows.extend(rows)
            except FloodWait as exc:
                register_account_runtime_event(
                    account=account,
                    event_type=AccountHealthEvent.EventType.FLOOD_WAIT,
                    severity=AccountHealthEvent.Severity.HIGH,
                    score_delta=-15,
                    reason=f"Comment parser FloodWait {getattr(exc, 'value', '')}s",
                    metadata={"job_id": job.id, "seconds": getattr(exc, "value", None)},
                )
                log_parser_event(
                    job,
                    level=CommentParserLog.Level.ERROR,
                    account=account,
                    message=f"{account.label}: FloodWait, акаунт відправлено в карантин",
                )
            except RPCError as exc:
                log_parser_event(
                    job,
                    level=CommentParserLog.Level.ERROR,
                    account=account,
                    message=f"{account.label}: Telegram error: {exc}",
                )
            request_delay = _random_delay(timing.request_delay_range)
            if request_delay:
                time.sleep(request_delay)
        _bulk_replace_results(job.id, all_rows)
        job.status = CommentParserJob.Status.SUCCEEDED
        job.finished_at = timezone.now()
        job.error = ""
        job.save(update_fields=["status", "finished_at", "error", "updated_at"])
        log_parser_event(
            job,
            level=CommentParserLog.Level.SUCCESS,
            message=f"Парсинг завершено. Знайдено {ParsedCommenter.objects.filter(job=job).count()} коментаторів",
        )
    except Exception as exc:
        job.status = CommentParserJob.Status.FAILED
        job.error = str(exc)
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error", "finished_at", "updated_at"])
        log_parser_event(job, level=CommentParserLog.Level.ERROR, message=f"Помилка парсингу: {exc}")
    return job


def export_results(job: CommentParserJob, *, export_format: str = "csv") -> tuple[str, str, str]:
    results = job.results.order_by("-comment_count", "-last_comment_at", "full_name")
    export_format = (export_format or "csv").lower()
    filename = f"comment-parser-{job.id}.{export_format}"
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
                "comment_count": result.comment_count,
                "matched_keywords": result.matched_keywords,
                "last_comment_at": result.last_comment_at.isoformat() if result.last_comment_at else None,
            }
            for result in results
        ]
        return filename, "application/json", json.dumps(payload, ensure_ascii=False, indent=2)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["full_name", "username", "profile_url", "source_title", "comment_count", "matched_keywords", "last_comment_at"])
    for result in results:
        writer.writerow(
            [
                result.full_name,
                result.username,
                result.profile_url,
                result.source_title,
                result.comment_count,
                ", ".join(result.matched_keywords or []),
                result.last_comment_at.isoformat() if result.last_comment_at else "",
            ]
        )
    return filename, "text/csv", output.getvalue()


def overview_payload(owner) -> dict[str, object]:
    jobs = (
        CommentParserJob.objects.filter(owner=owner)
        .annotate(result_count=Count("results", distinct=True), log_count=Count("logs", distinct=True))
        .prefetch_related("accounts")
        .order_by("-created_at")[:20]
    )
    latest_job = jobs[0] if jobs else None
    return {
        "jobs": jobs,
        "results": (
            ParsedCommenter.objects.filter(owner=owner, job=latest_job).order_by("-comment_count", "-last_comment_at", "full_name")[:500]
            if latest_job
            else []
        ),
        "logs": (
            CommentParserLog.objects.filter(owner=owner, job=latest_job).select_related("account").order_by("created_at")[:500]
            if latest_job
            else []
        ),
        "accounts": TelegramAccount.objects.filter(
            owner=owner, is_attached=True, auth_state=TelegramAccount.AuthState.CONNECTED
        ).select_related("proxy", "role_template"),
        "channel_templates": list(
            ChannelCollectionTemplate.objects.filter(owner=owner)
            .annotate(item_count=Count("items", distinct=True))
            .prefetch_related("items")
            .order_by("name", "-created_at")
        ),
        "templates": {
            "sales": ["товарка", "дропшипінг", "маркетплейс"],
            "crypto": ["крипта", "криптогаманець", "airdrop"],
            "growth": ["розкрутити Telegram-канал", "ліди", "реклама"],
        },
    }
