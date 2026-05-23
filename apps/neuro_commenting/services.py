from __future__ import annotations

import asyncio
import random
import re
import time

import requests
from asgiref.sync import sync_to_async
from celery.result import AsyncResult
from django.conf import settings
from django.utils import timezone
from pyrogram.errors import FloodWait, RPCError

from apps.neuro_commenting.models import (
    NeuroCommentBlacklist,
    NeuroCommentJob,
    NeuroCommentLog,
    NeuroCommentPrompt,
    SYSTEM_PROMPTS,
)
from apps.realtime.logging import publish_log_event
from apps.telegram_accounts.models import AccountHealthEvent, TelegramAccount
from apps.telegram_accounts.services import (
    get_account_runtime_block_reason,
    register_account_runtime_event,
    run_client_operation,
)


def _log(
    job: NeuroCommentJob | None,
    *,
    level: str,
    message: str,
    account: TelegramAccount | None = None,
    channel: str = "",
    post_text: str = "",
    comment_text: str = "",
    prompt_name: str = "",
    metadata: dict | None = None,
) -> NeuroCommentLog:
    owner = job.owner if job else (account.owner if account else None)
    log = NeuroCommentLog.objects.create(
        owner=owner,
        job=job,
        account=account,
        channel=channel,
        post_text=post_text[:500],
        comment_text=comment_text,
        prompt_name=prompt_name,
        level=level,
        message=message,
        metadata=metadata or {},
    )
    publish_log_event(
        {
            "level": level,
            "source": account.label if account else "neuro_commenting",
            "message": message,
            "metadata": {
                "module": "neuro_commenting",
                "job_id": job.id if job else None,
                "account_id": account.id if account else None,
                "channel": channel,
                "comment": comment_text,
                "prompt": prompt_name,
            },
        }
    )
    return log


async_log = sync_to_async(_log, thread_sensitive=True)


def _random_delay(min_s: float, max_s: float) -> float:
    min_s = max(0.0, float(min_s))
    max_s = max(min_s, float(max_s))
    return random.uniform(min_s, max_s) if max_s > 0 else 0.0


def _normalize_source(raw: str) -> str:
    value = str(raw or "").strip()
    if not value:
        return ""
    if value.lstrip("-").isdigit():
        return int(value)
    value = re.sub(r"^https?://t\.me/", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^t\.me/", "", value, flags=re.IGNORECASE)
    value = value.lstrip("@").split("?")[0].split("/")[0].strip()
    return value or raw


def _call_ai(system: str, user: str, *, max_tokens: int = 200, temperature: float = 0.8) -> str:
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


def _detect_language(text: str) -> str:
    cyrillic = len(re.findall(r"[а-яёА-ЯЁіїєІЇЄ]", text))
    latin = len(re.findall(r"[a-zA-Z]", text))
    if cyrillic > latin:
        return "ru"
    return "en"


async def _generate_comment(job: NeuroCommentJob, post_text: str, prompt: NeuroCommentPrompt | None) -> str:
    if not job.use_ai_prompt:
        return ""

    lang = job.language if job.language_mode == NeuroCommentJob.LanguageMode.MANUAL else _detect_language(post_text)
    lang_instruction = f" Пиши відповідь мовою: {lang}." if lang else ""

    if prompt:
        system = prompt.text + lang_instruction
    else:
        system = (
            "Напиши короткий, природній коментар до поста в Telegram-каналі. "
            "1–2 речення." + lang_instruction
        )

    user = f"Пост:\n{post_text[:800]}"
    return await async_call_ai(system, user, max_tokens=150, temperature=0.85)


def _should_comment(job: NeuroCommentJob, post_text: str) -> bool:
    if job.comment_mode == NeuroCommentJob.CommentMode.ALL:
        return True
    if job.comment_mode == NeuroCommentJob.CommentMode.RANDOM:
        return random.random() < job.random_probability
    if job.comment_mode == NeuroCommentJob.CommentMode.KEYWORD:
        text_lower = post_text.lower()
        return any(kw.lower() in text_lower for kw in (job.keywords or []) if kw)
    return True


def _is_blacklisted(job: NeuroCommentJob, channel_username: str) -> bool:
    return NeuroCommentBlacklist.objects.filter(
        owner=job.owner, channel_username__iexact=channel_username
    ).exists()


def _add_to_blacklist(
    job: NeuroCommentJob,
    account: TelegramAccount | None,
    channel_username: str,
    reason: str,
) -> None:
    NeuroCommentBlacklist.objects.get_or_create(
        owner=job.owner,
        channel_username=channel_username,
        defaults={"job": job, "account": account, "reason": reason},
    )


async_is_blacklisted = sync_to_async(_is_blacklisted, thread_sensitive=True)
async_add_to_blacklist = sync_to_async(_add_to_blacklist, thread_sensitive=True)


async def _comment_on_post(
    app,
    job: NeuroCommentJob,
    account: TelegramAccount,
    chat,
    message,
    prompt: NeuroCommentPrompt | None,
    comment_counter: list[int],
) -> bool:
    post_text = (getattr(message, "text", "") or getattr(message, "caption", "") or "").strip()
    if not _should_comment(job, post_text):
        return False

    comment_text = await _generate_comment(job, post_text, prompt)
    if not comment_text:
        comment_text = "Цікаво!"

    channel_title = getattr(chat, "title", str(chat.id)) or str(chat.id)
    channel_username = getattr(chat, "username", "") or str(chat.id)
    prompt_name = prompt.name if prompt else "default"

    try:
        if job.first_message_strategy and job.first_message_text:
            sent = await app.send_message(chat.id, job.first_message_text, reply_to_message_id=message.id)
            await asyncio.sleep(max(5, job.first_message_edit_delay))
            await sent.edit_text(comment_text)
        else:
            await app.send_message(chat.id, comment_text, reply_to_message_id=message.id)

        comment_counter[0] += 1
        await sync_to_async(NeuroCommentJob.objects.filter(pk=job.pk).update)(
            comments_sent=comment_counter[0]
        )
        await async_log(
            job,
            level=NeuroCommentLog.Level.SUCCESS,
            account=account,
            channel=channel_username,
            post_text=post_text,
            comment_text=comment_text,
            prompt_name=prompt_name,
            message=f"{account.label}: коментар у «{channel_title}» #{message.id}",
            metadata={"channel": channel_username, "message_id": message.id, "prompt": prompt_name},
        )
        return True
    except FloodWait:
        raise
    except Exception as exc:
        exc_str = str(exc)
        await async_log(
            job,
            level=NeuroCommentLog.Level.WARNING,
            account=account,
            channel=channel_username,
            message=f"{account.label}: не вдалося прокоментувати #{message.id}: {exc_str}",
        )
        if any(kw in exc_str.upper() for kw in ("BANNED", "RESTRICTED", "CHAT_WRITE_FORBIDDEN")):
            await async_add_to_blacklist(
                job, account, channel_username, NeuroCommentBlacklist.Reason.BANNED
            )
        return False


def _pick_prompt(job: NeuroCommentJob, prompts: list[NeuroCommentPrompt]) -> NeuroCommentPrompt | None:
    if not prompts:
        return None
    return random.choice(prompts)


async def _monitor_source(
    app,
    job: NeuroCommentJob,
    account: TelegramAccount,
    source: str,
    prompts: list[NeuroCommentPrompt],
    comment_counter: list[int],
    deadline: float | None,
) -> int:
    raw_source = _normalize_source(source)
    channel_username = str(raw_source).lstrip("@")

    if await async_is_blacklisted(job, channel_username):
        await async_log(
            job, level=NeuroCommentLog.Level.INFO, account=account,
            channel=channel_username,
            message=f"Канал {source} у чорному списку — пропускаємо",
        )
        return 0

    try:
        chat = await app.get_chat(raw_source)
    except Exception as exc:
        await async_log(
            job, level=NeuroCommentLog.Level.ERROR, account=account,
            channel=channel_username,
            message=f"{account.label}: не вдалося отримати канал {source}: {exc}",
        )
        return 0

    await async_log(
        job, level=NeuroCommentLog.Level.INFO, account=account,
        channel=getattr(chat, "username", "") or channel_username,
        message=f"{account.label}: моніторинг «{getattr(chat, 'title', source) or source}»",
    )

    seen_ids: set[int] = set()
    total = 0

    # seed seen IDs
    try:
        async for msg in app.get_chat_history(chat.id, limit=10):
            seen_ids.add(msg.id)
    except Exception:
        pass

    entry_delay = _random_delay(job.entry_delay_min, job.entry_delay_max)
    if entry_delay:
        await asyncio.sleep(entry_delay)

    while True:
        if deadline and time.monotonic() > deadline:
            break
        job_fresh = await sync_to_async(NeuroCommentJob.objects.get)(pk=job.pk)
        if job_fresh.status != NeuroCommentJob.Status.RUNNING:
            break
        if job.max_comments and comment_counter[0] >= job.max_comments:
            break

        try:
            async for message in app.get_chat_history(chat.id, limit=5):
                if message.id in seen_ids:
                    break
                seen_ids.add(message.id)

                delay = _random_delay(job.comment_delay_min, job.comment_delay_max)
                if delay:
                    await asyncio.sleep(delay)

                prompt = _pick_prompt(job, prompts)
                commented = await _comment_on_post(app, job, account, chat, message, prompt, comment_counter)
                if commented:
                    total += 1
        except FloodWait:
            raise
        except Exception:
            pass

        await asyncio.sleep(20)

    return total


async def _process_source_existing(
    app,
    job: NeuroCommentJob,
    account: TelegramAccount,
    source: str,
    prompts: list[NeuroCommentPrompt],
    comment_counter: list[int],
) -> int:
    raw_source = _normalize_source(source)
    channel_username = str(raw_source).lstrip("@")

    if await async_is_blacklisted(job, channel_username):
        return 0

    try:
        chat = await app.get_chat(raw_source)
    except Exception as exc:
        await async_log(
            job, level=NeuroCommentLog.Level.ERROR, account=account,
            channel=channel_username,
            message=f"{account.label}: не вдалося отримати канал {source}: {exc}",
        )
        return 0

    entry_delay = _random_delay(job.entry_delay_min, job.entry_delay_max)
    if entry_delay:
        await asyncio.sleep(entry_delay)

    total = 0
    limit = min(job.max_comments - comment_counter[0], 50) if job.max_comments else 50

    try:
        async for message in app.get_chat_history(chat.id, limit=limit):
            job_fresh = await sync_to_async(NeuroCommentJob.objects.get)(pk=job.pk)
            if job_fresh.status != NeuroCommentJob.Status.RUNNING:
                break
            if job.max_comments and comment_counter[0] >= job.max_comments:
                break

            delay = _random_delay(job.comment_delay_min, job.comment_delay_max)
            if delay:
                await asyncio.sleep(delay)

            prompt = _pick_prompt(job, prompts)
            commented = await _comment_on_post(app, job, account, chat, message, prompt, comment_counter)
            if commented:
                total += 1
    except FloodWait:
        raise
    except Exception as exc:
        await async_log(
            job, level=NeuroCommentLog.Level.ERROR, account=account,
            channel=channel_username,
            message=f"{account.label}: помилка в {source}: {exc}",
        )

    return total


def start_neuro_comment_job(job: NeuroCommentJob) -> NeuroCommentJob:
    from apps.neuro_commenting.tasks import run_neuro_comment_job_task

    if job.status == NeuroCommentJob.Status.RUNNING:
        return job
    job.status = NeuroCommentJob.Status.RUNNING
    job.error = ""
    job.comments_sent = 0
    job.started_at = timezone.now()
    job.finished_at = None
    job.save(update_fields=["status", "error", "comments_sent", "started_at", "finished_at", "updated_at"])
    task = run_neuro_comment_job_task.delay(job.id)
    job.celery_task_id = task.id
    job.save(update_fields=["celery_task_id", "updated_at"])
    _log(job, level=NeuroCommentLog.Level.INFO, message="Запуск модуля Нейрокоментинг")
    return job


def stop_neuro_comment_job(job: NeuroCommentJob) -> NeuroCommentJob:
    if job.celery_task_id:
        AsyncResult(job.celery_task_id).revoke(terminate=False)
    job.status = NeuroCommentJob.Status.STOPPED
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "finished_at", "updated_at"])
    _log(job, level=NeuroCommentLog.Level.SUCCESS, message="Задачу зупинено")
    return job


def run_neuro_comment_job(job_id: int) -> NeuroCommentJob:
    job = NeuroCommentJob.objects.prefetch_related("accounts", "selected_prompts").get(pk=job_id)
    accounts = list(
        job.accounts.filter(is_attached=True, auth_state=TelegramAccount.AuthState.CONNECTED)
    )
    if not accounts:
        raise RuntimeError("Немає валідних акаунтів для коментування.")

    sources = [str(s).strip() for s in (job.sources or []) if str(s).strip()]
    if not sources:
        raise RuntimeError("Немає джерел (каналів) для коментування.")

    prompts = list(job.selected_prompts.all())
    comment_counter: list[int] = [0]
    deadline: float | None = (
        time.monotonic() + job.duration_minutes * 60
        if job.work_mode == NeuroCommentJob.WorkMode.MONITORING and job.duration_minutes
        else None
    )

    account_rotation_counter = [0]

    def _pick_account() -> TelegramAccount:
        if not job.account_rotation:
            return accounts[0]
        idx = (account_rotation_counter[0] // max(1, job.rotation_every_n)) % len(accounts)
        account_rotation_counter[0] += 1
        return accounts[idx]

    try:
        if job.work_mode == NeuroCommentJob.WorkMode.MONITORING:
            # All accounts monitor all sources concurrently via sequential per-account loop
            for source in sources:
                job_fresh = NeuroCommentJob.objects.get(pk=job.pk)
                if job_fresh.status != NeuroCommentJob.Status.RUNNING:
                    break
                if job.max_comments and comment_counter[0] >= job.max_comments:
                    break

                account = _pick_account()
                block_reason = get_account_runtime_block_reason(account)
                if block_reason:
                    _log(
                        job, level=NeuroCommentLog.Level.WARNING, account=account,
                        message=f"{account.label}: пропущено: {block_reason}",
                    )
                    continue

                try:
                    run_client_operation(
                        account,
                        lambda app, s=source, a=account: _monitor_source(
                            app, job, a, s, prompts, comment_counter, deadline
                        ),
                    )
                except FloodWait as exc:
                    register_account_runtime_event(
                        account=account,
                        event_type=AccountHealthEvent.EventType.FLOOD_WAIT,
                        metadata={"job_id": job.id, "seconds": getattr(exc, "value", None)},
                    )
                    _log(
                        job, level=NeuroCommentLog.Level.ERROR, account=account,
                        message=f"{account.label}: FloodWait, акаунт відправлено в карантин",
                    )
                except RPCError as exc:
                    _log(
                        job, level=NeuroCommentLog.Level.ERROR, account=account,
                        message=f"{account.label}: Telegram error: {exc}",
                    )
        else:
            # BY COUNT — process existing posts
            for source in sources:
                job_fresh = NeuroCommentJob.objects.get(pk=job.pk)
                if job_fresh.status != NeuroCommentJob.Status.RUNNING:
                    break
                if job.max_comments and comment_counter[0] >= job.max_comments:
                    break

                account = _pick_account()
                block_reason = get_account_runtime_block_reason(account)
                if block_reason:
                    _log(
                        job, level=NeuroCommentLog.Level.WARNING, account=account,
                        message=f"{account.label}: пропущено: {block_reason}",
                    )
                    continue

                try:
                    run_client_operation(
                        account,
                        lambda app, s=source, a=account: _process_source_existing(
                            app, job, a, s, prompts, comment_counter
                        ),
                    )
                except FloodWait as exc:
                    register_account_runtime_event(
                        account=account,
                        event_type=AccountHealthEvent.EventType.FLOOD_WAIT,
                        metadata={"job_id": job.id, "seconds": getattr(exc, "value", None)},
                    )
                    _log(
                        job, level=NeuroCommentLog.Level.ERROR, account=account,
                        message=f"{account.label}: FloodWait, відправлено в карантин",
                    )
                except RPCError as exc:
                    _log(
                        job, level=NeuroCommentLog.Level.ERROR, account=account,
                        message=f"{account.label}: Telegram error: {exc}",
                    )

        job.refresh_from_db()
        if job.status == NeuroCommentJob.Status.RUNNING:
            job.status = NeuroCommentJob.Status.SUCCEEDED
            job.finished_at = timezone.now()
            job.error = ""
            job.save(update_fields=["status", "finished_at", "error", "updated_at"])
            _log(
                job, level=NeuroCommentLog.Level.SUCCESS,
                message=f"Готово. Надіслано коментарів: {comment_counter[0]}",
            )
    except Exception as exc:
        job.status = NeuroCommentJob.Status.FAILED
        job.error = str(exc)
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error", "finished_at", "updated_at"])
        _log(job, level=NeuroCommentLog.Level.ERROR, message=f"Помилка: {exc}")

    return job


def ensure_system_prompts(owner) -> list[NeuroCommentPrompt]:
    result = []
    for key, name, text in SYSTEM_PROMPTS:
        prompt, _ = NeuroCommentPrompt.objects.get_or_create(
            owner=owner,
            name=name,
            defaults={"text": text, "is_system": True},
        )
        result.append(prompt)
    return result


def overview_payload(owner) -> dict:
    from django.db.models import Count

    jobs = (
        NeuroCommentJob.objects.filter(owner=owner)
        .annotate(log_count=Count("logs", distinct=True))
        .prefetch_related("accounts", "selected_prompts")
        .order_by("-created_at")[:20]
    )
    latest_job = jobs[0] if jobs else None
    accounts = TelegramAccount.objects.filter(
        owner=owner, is_attached=True, auth_state=TelegramAccount.AuthState.CONNECTED
    ).select_related("proxy", "role_template")
    system_prompts = ensure_system_prompts(owner)
    user_prompts = list(
        NeuroCommentPrompt.objects.filter(owner=owner, is_system=False).order_by("name")
    )
    blacklist = NeuroCommentBlacklist.objects.filter(owner=owner).select_related("account", "job").order_by("-created_at")[:100]
    return {
        "jobs": list(jobs),
        "logs": (
            list(
                NeuroCommentLog.objects.filter(owner=owner, job=latest_job)
                .select_related("account")
                .order_by("created_at")[:500]
            )
            if latest_job else []
        ),
        "accounts": list(accounts),
        "system_prompts": system_prompts,
        "user_prompts": user_prompts,
        "blacklist": list(blacklist),
    }
