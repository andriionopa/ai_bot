from __future__ import annotations

import asyncio
import random
import re
import time
from datetime import datetime, timezone as dt_timezone

import requests
from asgiref.sync import sync_to_async
from celery.result import AsyncResult
from django.conf import settings
from django.db.models import F
from django.utils import timezone
from pyrogram import raw
from pyrogram.errors import (
    AuthKeyUnregistered,
    ChatWriteForbidden,
    FloodWait,
    PeerFlood,
    RPCError,
    SessionRevoked,
    SlowmodeWait,
    UserBannedInChannel,
    UserDeactivated,
)

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

POLL_INTERVAL_SECONDS = 20
INTERRUPTIBLE_TICK_SECONDS = 2.0
TYPING_CHARS_PER_SECOND = 30
TYPING_MAX_SECONDS = 8.0
TYPING_MIN_SECONDS = 1.0
DEFAULT_MONITORING_FALLBACK_MINUTES = 60


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


def _job_is_running(job_id: int) -> bool:
    return NeuroCommentJob.objects.filter(
        pk=job_id, status=NeuroCommentJob.Status.RUNNING
    ).exists()


async_job_is_running = sync_to_async(_job_is_running, thread_sensitive=True)


def _interruptible_wait_sync(job_id: int, seconds: float) -> bool:
    """Sleep up to `seconds` in small ticks, abort early if job stopped. Returns True if completed fully."""
    remaining = max(0.0, float(seconds))
    while remaining > 0:
        if not _job_is_running(job_id):
            return False
        chunk = min(INTERRUPTIBLE_TICK_SECONDS, remaining)
        time.sleep(chunk)
        remaining -= chunk
    return True


async def _interruptible_wait_async(job_id: int, seconds: float) -> bool:
    remaining = max(0.0, float(seconds))
    while remaining > 0:
        if not await async_job_is_running(job_id):
            return False
        chunk = min(INTERRUPTIBLE_TICK_SECONDS, remaining)
        await asyncio.sleep(chunk)
        remaining -= chunk
    return True


def _random_delay(min_s: float, max_s: float) -> float:
    min_s = max(0.0, float(min_s))
    max_s = max(min_s, float(max_s))
    return random.uniform(min_s, max_s) if max_s > 0 else 0.0


# ai_protection: when True, layered safe behaviour overrides user-defined timing.
# Matches the pattern in reaction_bot/comment_parser/channel_parser, plus extra Telegram-specific guards.
AI_PROTECTION_COMMENT_DELAY = (60.0, 180.0)
AI_PROTECTION_ENTRY_DELAY = (90.0, 240.0)
AI_PROTECTION_POST_AGE_FLOOR = (60.0, 300.0)  # min seconds since message.date before commenting
AI_PROTECTION_SKIP_PROBABILITY = 0.10  # 10% posts dropped to avoid 100% coverage signature
AI_PROTECTION_READ_HISTORY_PROB = 0.6  # chance to scroll/read before commenting
AI_PROTECTION_SCROLL_DEPTH = (5, 20)
AI_PROTECTION_QUIET_HOURS = (2, 7)  # local-tz quiet window [start, end)
AI_PROTECTION_BURST_WINDOW_MIN = 60  # rolling window length in minutes
AI_PROTECTION_BURST_LIMIT = 15  # max comments per account inside the window
AI_PROTECTION_BURST_COOLDOWN = (1200, 2400)  # 20–40 min cooldown


def _effective_delays(job: NeuroCommentJob) -> tuple[float, float, float, float]:
    """Returns (comment_min, comment_max, entry_min, entry_max). ai_protection forces safe ranges."""
    if job.ai_protection:
        return (*AI_PROTECTION_COMMENT_DELAY, *AI_PROTECTION_ENTRY_DELAY)
    return (
        job.comment_delay_min,
        job.comment_delay_max,
        job.entry_delay_min,
        job.entry_delay_max,
    )


def _in_quiet_hours(now: datetime | None = None) -> bool:
    now = now or timezone.localtime()
    start, end = AI_PROTECTION_QUIET_HOURS
    return start <= now.hour < end


def _message_age_seconds(message) -> float:
    raw_date = getattr(message, "date", None)
    if raw_date is None:
        return 0.0
    if isinstance(raw_date, datetime):
        if raw_date.tzinfo is None:
            raw_date = raw_date.replace(tzinfo=dt_timezone.utc)
        return max(0.0, (datetime.now(tz=dt_timezone.utc) - raw_date).total_seconds())
    try:
        return max(0.0, time.time() - float(raw_date))
    except (TypeError, ValueError):
        return 0.0


def _account_recent_comment_count(job_id: int, account_id: int, minutes: int) -> int:
    from datetime import timedelta

    since = timezone.now() - timedelta(minutes=minutes)
    return NeuroCommentLog.objects.filter(
        job_id=job_id,
        account_id=account_id,
        level=NeuroCommentLog.Level.SUCCESS,
        created_at__gte=since,
    ).count()


def _post_already_commented(job_id: int, channel_username: str, message_id: int) -> bool:
    return NeuroCommentLog.objects.filter(
        job_id=job_id,
        level=NeuroCommentLog.Level.SUCCESS,
        channel=channel_username,
        metadata__message_id=message_id,
    ).exists()


async_account_recent_comment_count = sync_to_async(_account_recent_comment_count, thread_sensitive=True)
async_post_already_commented = sync_to_async(_post_already_commented, thread_sensitive=True)


def _typing_seconds(text: str) -> float:
    if not text:
        return TYPING_MIN_SECONDS
    raw = len(text) / TYPING_CHARS_PER_SECOND
    return min(TYPING_MAX_SECONDS, max(TYPING_MIN_SECONDS, raw))


def _normalize_source(raw_value: str) -> str:
    value = str(raw_value or "").strip()
    if not value:
        return ""
    if value.lstrip("-").isdigit():
        return int(value)
    value = re.sub(r"^https?://t\.me/", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^t\.me/", "", value, flags=re.IGNORECASE)
    value = value.lstrip("@").split("?")[0].split("/")[0].strip()
    return value or raw_value


def _is_addlist_source(value: str) -> bool:
    return "addlist/" in str(value or "")


def _extract_addlist_slug(value: str) -> str:
    """Extract the slug from a t.me/addlist/<slug> link."""
    match = re.search(r"(?:https?://)?t\.me/addlist/([A-Za-z0-9_\-]+)", str(value or ""))
    if not match:
        raise RuntimeError("Некоректне посилання addlist. Очікується формат https://t.me/addlist/...")
    return match.group(1)


def _peer_username_or_id(peer, *, chats_by_id: dict[int, object]) -> str:
    """Convert a chatlist peer into something _normalize_source can later resolve."""
    if isinstance(peer, raw.types.PeerChannel):
        chat = chats_by_id.get(peer.channel_id)
        username = (
            getattr(chat, "username", "")
            or (getattr(chat, "usernames", []) and getattr(chat.usernames[0], "username", ""))
            or ""
        )
        if username:
            return f"@{username}"
        # private/no-username channel — fall back to the bare channel_id; Pyrogram expects
        # the -100... form for raw channel ids.
        return f"-100{peer.channel_id}"
    if isinstance(peer, raw.types.PeerChat):
        return f"-{peer.chat_id}"
    return ""


async def _resolve_and_join_addlist(app, source: str) -> tuple[list[str], dict]:
    """For a single t.me/addlist/<slug> source, run CheckChatlistInvite + JoinChatlistInvite
    on the given client. Returns (resolved_source_refs, info_dict). Idempotent — if the
    account already joined the folder, no new join is performed but peers are still returned."""
    slug = _extract_addlist_slug(source)
    invite = await app.invoke(raw.functions.chatlists.CheckChatlistInvite(slug=slug))
    chats_by_id = {getattr(chat, "id", None): chat for chat in (getattr(invite, "chats", []) or [])}

    new_peers = list(getattr(invite, "peers", []) or [])
    missing_peers = list(getattr(invite, "missing_peers", []) or [])
    already_peers = list(getattr(invite, "already_peers", []) or [])

    # Collect every peer we can identify so the bot can comment in them regardless of
    # whether this account already had them in its dialogs.
    seen_keys = set()
    all_peers = []
    for bucket in (new_peers, missing_peers, already_peers):
        for peer in bucket:
            key = None
            if isinstance(peer, raw.types.PeerChannel):
                key = ("channel", peer.channel_id)
            elif isinstance(peer, raw.types.PeerChat):
                key = ("chat", peer.chat_id)
            if key is None or key in seen_keys:
                continue
            seen_keys.add(key)
            all_peers.append(peer)

    refs: list[str] = []
    for peer in all_peers:
        ref = _peer_username_or_id(peer, chats_by_id=chats_by_id)
        if ref:
            refs.append(ref)

    joined_count = 0
    # Issue JoinChatlistInvite only if the folder has not been accepted yet AND there are
    # peers we can actually pass (need access_hash for channels/users).
    if new_peers or missing_peers:
        input_peers = []
        for peer in (*new_peers, *missing_peers):
            if isinstance(peer, raw.types.PeerChannel):
                chat = chats_by_id.get(peer.channel_id)
                access_hash = getattr(chat, "access_hash", None)
                if access_hash is None:
                    continue
                input_peers.append(
                    raw.types.InputPeerChannel(channel_id=peer.channel_id, access_hash=access_hash)
                )
            elif isinstance(peer, raw.types.PeerChat):
                input_peers.append(raw.types.InputPeerChat(chat_id=peer.chat_id))
        if input_peers:
            await app.invoke(
                raw.functions.chatlists.JoinChatlistInvite(slug=slug, peers=input_peers)
            )
            joined_count = len(input_peers)

    return refs, {
        "slug": slug,
        "folder_title": getattr(invite, "title", "") or "",
        "joined_count": joined_count,
        "already_count": len(already_peers),
        "total_channels": len(refs),
    }


def _resolve_folder_sources(
    job: NeuroCommentJob,
    accounts: list[TelegramAccount],
    addlist_sources: list[str],
) -> list[str]:
    """For each addlist link, ask the first reachable account to resolve it (one network
    round-trip) and try to join the folder from every other account so they can comment
    inside the folder's channels. Returns the de-duplicated list of resolved channel
    references that should be merged into job.sources."""
    resolved: list[str] = []
    for source in addlist_sources:
        first_resolved_refs: list[str] | None = None
        for account in accounts:
            if get_account_runtime_block_reason(account):
                continue
            try:
                refs, info = run_client_operation(
                    account, lambda app, s=source: _resolve_and_join_addlist(app, s)
                )
            except FloodWait as exc:
                _handle_account_exception(job, account, exc)
                continue
            except (RPCError, RuntimeError) as exc:
                _log(
                    job,
                    level=NeuroCommentLog.Level.WARNING,
                    account=account,
                    message=f"{account.label}: не вдалося обробити папку {source}: {exc}",
                )
                continue
            except Exception as exc:
                _log(
                    job,
                    level=NeuroCommentLog.Level.WARNING,
                    account=account,
                    message=f"{account.label}: помилка папки {source}: {exc}",
                )
                continue

            if first_resolved_refs is None:
                first_resolved_refs = refs
                _log(
                    job,
                    level=NeuroCommentLog.Level.INFO,
                    account=account,
                    message=(
                        f"{account.label}: папка «{info.get('folder_title') or '?'}» — "
                        f"{info.get('total_channels', 0)} каналів, "
                        f"приєднано {info.get('joined_count', 0)}, вже у папці {info.get('already_count', 0)}"
                    ),
                    metadata={"addlist_slug": info.get("slug"), **info},
                )
            else:
                # subsequent accounts: just log the join action without re-resolving
                _log(
                    job,
                    level=NeuroCommentLog.Level.INFO,
                    account=account,
                    message=(
                        f"{account.label}: приєднано до папки «{info.get('folder_title') or '?'}» "
                        f"(нових: {info.get('joined_count', 0)})"
                    ),
                )
        if first_resolved_refs is None:
            _log(
                job,
                level=NeuroCommentLog.Level.WARNING,
                message=f"Папку {source} не вдалося розгорнути жодним акаунтом — пропускаємо",
            )
            continue
        resolved.extend(first_resolved_refs)

    # de-duplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for ref in resolved:
        key = ref.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(ref)
    return unique


def _call_ai(
    system: str, user: str, *, max_tokens: int = 200, temperature: float = 0.8
) -> tuple[str, str]:
    """Returns (text, error). On success error == ''. On failure text == ''."""
    base_url = getattr(settings, "PROFILE_TEXT_BASE_URL", "") or ""
    api_key = getattr(settings, "PROFILE_TEXT_API_KEY", "") or ""
    model = getattr(settings, "PROFILE_TEXT_MODEL", "gpt-4o-mini") or "gpt-4o-mini"
    if not base_url or not api_key:
        return "", "AI provider is not configured (PROFILE_TEXT_BASE_URL/API_KEY missing)"
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
        return resp.json()["choices"][0]["message"]["content"].strip(), ""
    except requests.HTTPError as exc:
        body = ""
        try:
            body = exc.response.text[:200] if exc.response is not None else ""
        except Exception:
            pass
        return "", f"HTTP {getattr(exc.response, 'status_code', '?')}: {body or exc}"
    except requests.RequestException as exc:
        return "", f"network: {exc}"
    except (KeyError, ValueError, IndexError) as exc:
        return "", f"unexpected provider response: {exc}"
    except Exception as exc:
        return "", f"{type(exc).__name__}: {exc}"


async_call_ai = sync_to_async(_call_ai, thread_sensitive=False)


def _detect_language(text: str) -> str:
    cyrillic = len(re.findall(r"[а-яёА-ЯЁіїєІЇЄ]", text))
    latin = len(re.findall(r"[a-zA-Z]", text))
    if cyrillic > latin:
        return "ru"
    return "en"


async def _generate_comment(
    job: NeuroCommentJob,
    post_text: str,
    prompt: NeuroCommentPrompt | None,
    *,
    account: TelegramAccount,
    channel: str,
) -> str:
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
    text, error = await async_call_ai(system, user, max_tokens=150, temperature=0.85)
    if error:
        await async_log(
            job,
            level=NeuroCommentLog.Level.WARNING,
            account=account,
            channel=channel,
            message=f"AI generation failed: {error}",
            metadata={"prompt": prompt.name if prompt else "default"},
        )
    return text


def _should_comment(job: NeuroCommentJob, post_text: str) -> bool:
    if job.comment_mode == NeuroCommentJob.CommentMode.ALL:
        base_decision = True
    elif job.comment_mode == NeuroCommentJob.CommentMode.RANDOM:
        base_decision = random.random() < job.random_probability
    elif job.comment_mode == NeuroCommentJob.CommentMode.KEYWORD:
        text_lower = post_text.lower()
        base_decision = any(kw.lower() in text_lower for kw in (job.keywords or []) if kw)
    else:
        base_decision = True

    if not base_decision:
        return False
    # ai_protection: drop a fraction of posts even in ALL/keyword modes so we don't
    # produce a 100%-coverage signature that admins can spot.
    if job.ai_protection and random.random() < AI_PROTECTION_SKIP_PROBABILITY:
        return False
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


def _increment_comments_sent(job_id: int) -> int:
    NeuroCommentJob.objects.filter(pk=job_id).update(
        comments_sent=F("comments_sent") + 1, updated_at=timezone.now()
    )
    return NeuroCommentJob.objects.filter(pk=job_id).values_list("comments_sent", flat=True).first() or 0


async_is_blacklisted = sync_to_async(_is_blacklisted, thread_sensitive=True)
async_add_to_blacklist = sync_to_async(_add_to_blacklist, thread_sensitive=True)
async_increment_comments_sent = sync_to_async(_increment_comments_sent, thread_sensitive=True)


async def _send_typing(app, chat_id) -> None:
    from pyrogram.enums import ChatAction

    try:
        await app.send_chat_action(chat_id, ChatAction.TYPING)
    except Exception:
        # typing is a UX nicety; don't fail the comment if it fails
        pass


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

    channel_title = getattr(chat, "title", str(chat.id)) or str(chat.id)
    channel_username = getattr(chat, "username", "") or str(chat.id)
    prompt_name = prompt.name if prompt else "default"

    # ai_protection: guard against another account on the same job already commenting
    # on this exact post (would look like a coordinated wave to admins).
    if job.ai_protection and await async_post_already_commented(
        job.id, channel_username, message.id
    ):
        return False

    # ai_protection: enforce a minimum age for the post — humans don't comment 3s
    # after publication. Wait out the floor with an interruptible sleep.
    if job.ai_protection:
        floor_min, floor_max = AI_PROTECTION_POST_AGE_FLOOR
        required_age = random.uniform(floor_min, floor_max)
        age = _message_age_seconds(message)
        if age < required_age:
            wait_left = required_age - age
            if not await _interruptible_wait_async(job.id, wait_left):
                return False

    # ai_protection: slow-mode aware delay. Pyrogram exposes slow_mode_delay on
    # Chat; if the chat enforces N seconds between messages, pad by 20%.
    slow_mode = getattr(chat, "slow_mode_delay", None) or 0
    if slow_mode:
        pad = slow_mode * 1.2
        if not await _interruptible_wait_async(job.id, pad):
            return False

    # ai_protection: produce realistic readHistory telemetry before sending —
    # mark the post as read, optionally scroll through nearby history.
    if job.ai_protection and random.random() < AI_PROTECTION_READ_HISTORY_PROB:
        try:
            await app.read_chat_history(chat.id, message.id)
        except Exception:
            pass
        try:
            depth = random.randint(*AI_PROTECTION_SCROLL_DEPTH)
            scrolled = 0
            async for _ in app.get_chat_history(chat.id, limit=depth):
                scrolled += 1
        except Exception:
            pass

    comment_text = await _generate_comment(
        job, post_text, prompt, account=account, channel=channel_username
    )
    if not comment_text:
        comment_text = "Цікаво!"

    try:
        if job.first_message_strategy and job.first_message_text:
            await _send_typing(app, chat.id)
            # short typing for emoji
            await _interruptible_wait_async(job.id, TYPING_MIN_SECONDS)
            sent = await app.send_message(
                chat.id, job.first_message_text, reply_to_message_id=message.id
            )
            edit_delay = max(5, job.first_message_edit_delay)
            completed = await _interruptible_wait_async(job.id, edit_delay)
            if not completed:
                # job stopped mid-wait: try to clean up the emoji to avoid noise
                try:
                    await app.delete_messages(chat.id, sent.id)
                except Exception:
                    pass
                return False
            await _send_typing(app, chat.id)
            await _interruptible_wait_async(job.id, _typing_seconds(comment_text))
            try:
                await sent.edit_text(comment_text)
            except Exception as edit_exc:
                # rollback the placeholder so we don't leave a stray emoji in the chat
                try:
                    await app.delete_messages(chat.id, sent.id)
                except Exception:
                    pass
                await async_log(
                    job,
                    level=NeuroCommentLog.Level.WARNING,
                    account=account,
                    channel=channel_username,
                    message=(
                        f"{account.label}: edit після емоджі провалився, повідомлення відкочено: {edit_exc}"
                    ),
                )
                return False
        else:
            await _send_typing(app, chat.id)
            await _interruptible_wait_async(job.id, _typing_seconds(comment_text))
            await app.send_message(chat.id, comment_text, reply_to_message_id=message.id)

        new_total = await async_increment_comments_sent(job.id)
        comment_counter[0] = new_total
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


class AccountRotator:
    """Round-robin account picker that switches every `every_n` comments."""

    def __init__(self, accounts: list[TelegramAccount], every_n: int | None) -> None:
        if not accounts:
            raise ValueError("AccountRotator requires at least one account")
        self.accounts = accounts
        self.every_n = max(1, every_n) if every_n else None
        self._idx = 0
        self._streak = 0

    def current(self) -> TelegramAccount:
        return self.accounts[self._idx % len(self.accounts)]

    def mark_comment(self) -> None:
        if not self.every_n:
            return
        self._streak += 1
        if self._streak >= self.every_n:
            self._streak = 0
            self._idx = (self._idx + 1) % len(self.accounts)

    def skip_current(self) -> None:
        """Move to the next account without counting a comment (e.g. quarantined account)."""
        self._streak = 0
        self._idx = (self._idx + 1) % len(self.accounts)


async def _monitor_source_chunk(
    app,
    job: NeuroCommentJob,
    account: TelegramAccount,
    source: str,
    prompts: list[NeuroCommentPrompt],
    comment_counter: list[int],
    seen_ids: set[int],
    max_chunk: int,
    deadline: float | None,
) -> int:
    raw_source = _normalize_source(source)
    channel_username = str(raw_source).lstrip("@")

    if await async_is_blacklisted(job, channel_username):
        return 0

    try:
        chat = await app.get_chat(raw_source)
    except Exception as exc:
        await async_log(
            job,
            level=NeuroCommentLog.Level.ERROR,
            account=account,
            channel=channel_username,
            message=f"{account.label}: не вдалося отримати канал {source}: {exc}",
        )
        return 0

    comment_min, comment_max, entry_min, entry_max = _effective_delays(job)

    # Seed seen_ids on first visit to avoid commenting old posts.
    if not seen_ids:
        try:
            async for msg in app.get_chat_history(chat.id, limit=10):
                seen_ids.add(msg.id)
        except Exception:
            pass
        await async_log(
            job,
            level=NeuroCommentLog.Level.INFO,
            account=account,
            channel=getattr(chat, "username", "") or channel_username,
            message=f"{account.label}: моніторинг «{getattr(chat, 'title', source) or source}»",
        )
        entry_delay = _random_delay(entry_min, entry_max)
        if entry_delay:
            if not await _interruptible_wait_async(job.id, entry_delay):
                return 0

    chunk_done = 0
    try:
        new_messages = []
        async for message in app.get_chat_history(chat.id, limit=20):
            if message.id in seen_ids:
                continue
            new_messages.append(message)
        # process oldest-first so we don't skip messages on the next pass
        for message in reversed(new_messages):
            if not await async_job_is_running(job.id):
                break
            if deadline and time.monotonic() > deadline:
                break
            if job.max_comments and comment_counter[0] >= job.max_comments:
                break

            seen_ids.add(message.id)

            delay = _random_delay(comment_min, comment_max)
            if delay and not await _interruptible_wait_async(job.id, delay):
                break

            prompt = _pick_prompt(job, prompts)
            if await _comment_on_post(app, job, account, chat, message, prompt, comment_counter):
                chunk_done += 1
                if chunk_done >= max_chunk:
                    break
    except FloodWait:
        raise

    return chunk_done


async def _process_source_existing_chunk(
    app,
    job: NeuroCommentJob,
    account: TelegramAccount,
    source: str,
    prompts: list[NeuroCommentPrompt],
    comment_counter: list[int],
    processed_ids: set[int],
    max_chunk: int,
) -> tuple[int, bool]:
    """Returns (done, exhausted). `exhausted=True` means no more candidate messages in this channel."""
    raw_source = _normalize_source(source)
    channel_username = str(raw_source).lstrip("@")

    if await async_is_blacklisted(job, channel_username):
        return 0, True

    try:
        chat = await app.get_chat(raw_source)
    except Exception as exc:
        await async_log(
            job,
            level=NeuroCommentLog.Level.ERROR,
            account=account,
            channel=channel_username,
            message=f"{account.label}: не вдалося отримати канал {source}: {exc}",
        )
        return 0, True

    comment_min, comment_max, entry_min, entry_max = _effective_delays(job)

    if not processed_ids:
        entry_delay = _random_delay(entry_min, entry_max)
        if entry_delay and not await _interruptible_wait_async(job.id, entry_delay):
            return 0, False

    remaining_global = (
        max(0, job.max_comments - comment_counter[0]) if job.max_comments else 50
    )
    limit = min(max_chunk, remaining_global, 50)
    if limit <= 0:
        return 0, True

    chunk_done = 0
    exhausted = True  # flip to False if we hit our limit before running out of messages
    try:
        candidate_count = 0
        async for message in app.get_chat_history(chat.id, limit=50):
            if not await async_job_is_running(job.id):
                break
            if job.max_comments and comment_counter[0] >= job.max_comments:
                break
            if message.id in processed_ids:
                continue
            processed_ids.add(message.id)
            candidate_count += 1

            delay = _random_delay(comment_min, comment_max)
            if delay and not await _interruptible_wait_async(job.id, delay):
                break

            prompt = _pick_prompt(job, prompts)
            if await _comment_on_post(app, job, account, chat, message, prompt, comment_counter):
                chunk_done += 1
                if chunk_done >= limit:
                    exhausted = False
                    break
    except FloodWait:
        raise
    except Exception as exc:
        await async_log(
            job,
            level=NeuroCommentLog.Level.ERROR,
            account=account,
            channel=channel_username,
            message=f"{account.label}: помилка в {source}: {exc}",
        )

    return chunk_done, exhausted


def _handle_account_exception(
    job: NeuroCommentJob,
    account: TelegramAccount,
    exc: Exception,
    *,
    channel_username: str = "",
) -> None:
    """Classify a runtime error and route it: either quarantine the account, blacklist the
    channel for this owner, or just log it. Mirrors the carantine semantics of
    register_account_runtime_event (FLOOD_WAIT and PEER_FLOOD both trigger 24h quarantine
    via the SPAM_BLOCK / FLOOD_WAIT event types)."""
    if isinstance(exc, FloodWait):
        register_account_runtime_event(
            account=account,
            event_type=AccountHealthEvent.EventType.FLOOD_WAIT,
            metadata={"job_id": job.id, "seconds": getattr(exc, "value", None)},
        )
        _log(
            job,
            level=NeuroCommentLog.Level.ERROR,
            account=account,
            message=f"{account.label}: FloodWait ({getattr(exc, 'value', '?')}с), акаунт у карантині",
        )
        return
    if isinstance(exc, PeerFlood):
        # PEER_FLOOD = "Too many requests to peers" — Telegram's spam classifier flagged
        # this account. Treat as SPAM_BLOCK so the account goes into 24h quarantine.
        register_account_runtime_event(
            account=account,
            event_type=AccountHealthEvent.EventType.SPAM_BLOCK,
            metadata={"job_id": job.id, "exception": "PeerFlood"},
        )
        _log(
            job,
            level=NeuroCommentLog.Level.ERROR,
            account=account,
            message=f"{account.label}: PEER_FLOOD — акаунт у карантині (24h)",
        )
        return
    if isinstance(exc, SlowmodeWait):
        _log(
            job,
            level=NeuroCommentLog.Level.WARNING,
            account=account,
            channel=channel_username,
            message=(
                f"{account.label}: SlowmodeWait {getattr(exc, 'value', '?')}с — "
                f"наступний коментар у цьому каналі затримається"
            ),
        )
        return
    if isinstance(exc, (ChatWriteForbidden, UserBannedInChannel)):
        # Channel-level block, not an account problem — blacklist so we don't retry.
        if channel_username:
            _add_to_blacklist(job, account, channel_username, NeuroCommentBlacklist.Reason.BANNED)
        _log(
            job,
            level=NeuroCommentLog.Level.ERROR,
            account=account,
            channel=channel_username,
            message=f"{account.label}: бан у каналі {channel_username or '?'} ({type(exc).__name__})",
        )
        return
    if isinstance(exc, (AuthKeyUnregistered, SessionRevoked, UserDeactivated)):
        # Session is dead — flip auth_state so the farm overview surfaces this.
        TelegramAccount.objects.filter(pk=account.pk).update(
            auth_state=TelegramAccount.AuthState.DISCONNECTED
        )
        _log(
            job,
            level=NeuroCommentLog.Level.ERROR,
            account=account,
            message=f"{account.label}: сесія недійсна ({type(exc).__name__}), переведено в DISCONNECTED",
        )
        return
    if isinstance(exc, RPCError):
        _log(
            job,
            level=NeuroCommentLog.Level.ERROR,
            account=account,
            channel=channel_username,
            message=f"{account.label}: Telegram error: {exc}",
        )
        return
    _log(
        job,
        level=NeuroCommentLog.Level.ERROR,
        account=account,
        channel=channel_username,
        message=f"{account.label}: непередбачена помилка: {exc}",
    )


def _run_monitoring(
    job: NeuroCommentJob,
    rotator: AccountRotator,
    sources: list[str],
    prompts: list[NeuroCommentPrompt],
    comment_counter: list[int],
    deadline: float | None,
) -> None:
    seen_by_channel: dict[str, set[int]] = {}
    max_chunk = rotator.every_n or 1

    while _job_is_running(job.id):
        if deadline and time.monotonic() > deadline:
            break
        if job.max_comments and comment_counter[0] >= job.max_comments:
            break

        # ai_protection: skip the whole round during quiet hours (default 02:00–07:00).
        if job.ai_protection and _in_quiet_hours():
            _log(
                job,
                level=NeuroCommentLog.Level.INFO,
                message=f"Тихі години {AI_PROTECTION_QUIET_HOURS[0]}-{AI_PROTECTION_QUIET_HOURS[1]} — раунд пропущено",
            )
            if not _interruptible_wait_sync(job.id, 15 * 60):
                break
            continue

        round_progress = 0
        consecutive_blocked = 0
        for source in sources:
            if not _job_is_running(job.id):
                break
            if deadline and time.monotonic() > deadline:
                break
            if job.max_comments and comment_counter[0] >= job.max_comments:
                break

            account = rotator.current()
            block_reason = get_account_runtime_block_reason(account)
            if block_reason:
                _log(
                    job,
                    level=NeuroCommentLog.Level.WARNING,
                    account=account,
                    message=f"{account.label}: пропущено: {block_reason}",
                )
                rotator.skip_current()
                consecutive_blocked += 1
                if consecutive_blocked >= len(rotator.accounts):
                    _log(
                        job,
                        level=NeuroCommentLog.Level.ERROR,
                        message="Усі акаунти заблоковані — зупиняємо моніторинг",
                    )
                    return
                continue
            consecutive_blocked = 0

            # ai_protection: burst guard — if this account has written too many comments
            # in the rolling window, rotate past it and let it cool down.
            if job.ai_protection:
                recent = _account_recent_comment_count(
                    job.id, account.id, AI_PROTECTION_BURST_WINDOW_MIN
                )
                if recent >= AI_PROTECTION_BURST_LIMIT:
                    _log(
                        job,
                        level=NeuroCommentLog.Level.INFO,
                        account=account,
                        message=(
                            f"{account.label}: ліміт сплеску {AI_PROTECTION_BURST_LIMIT}/"
                            f"{AI_PROTECTION_BURST_WINDOW_MIN}хв — пропускаємо до охолодження"
                        ),
                    )
                    rotator.skip_current()
                    continue

            channel_key = str(_normalize_source(source)).lstrip("@")
            seen_ids = seen_by_channel.setdefault(channel_key, set())

            try:
                done = run_client_operation(
                    account,
                    lambda app, s=source, a=account, sids=seen_ids: _monitor_source_chunk(
                        app, job, a, s, prompts, comment_counter, sids, max_chunk, deadline
                    ),
                )
            except (FloodWait, RPCError) as exc:
                _handle_account_exception(job, account, exc, channel_username=channel_key)
                continue
            except Exception as exc:
                _handle_account_exception(job, account, exc, channel_username=channel_key)
                continue

            for _ in range(int(done or 0)):
                rotator.mark_comment()
            round_progress += int(done or 0)

        # poll cadence: short interruptible wait before the next round
        if not _interruptible_wait_sync(job.id, POLL_INTERVAL_SECONDS):
            break
        # if absolutely nothing happened in a round, don't busy-loop too tightly
        if round_progress == 0:
            _interruptible_wait_sync(job.id, POLL_INTERVAL_SECONDS)


def _run_by_count(
    job: NeuroCommentJob,
    rotator: AccountRotator,
    sources: list[str],
    prompts: list[NeuroCommentPrompt],
    comment_counter: list[int],
) -> None:
    processed_by_channel: dict[str, set[int]] = {}
    exhausted_channels: set[str] = set()
    max_chunk = rotator.every_n or 1

    while _job_is_running(job.id):
        if job.max_comments and comment_counter[0] >= job.max_comments:
            break

        active_sources = [s for s in sources if str(_normalize_source(s)).lstrip("@") not in exhausted_channels]
        if not active_sources:
            break

        # ai_protection: skip rounds during quiet hours (default 02:00–07:00 local TZ).
        if job.ai_protection and _in_quiet_hours():
            _log(
                job,
                level=NeuroCommentLog.Level.INFO,
                message=f"Тихі години {AI_PROTECTION_QUIET_HOURS[0]}-{AI_PROTECTION_QUIET_HOURS[1]} — раунд пропущено",
            )
            if not _interruptible_wait_sync(job.id, 15 * 60):
                break
            continue

        round_progress = 0
        consecutive_blocked = 0
        for source in active_sources:
            if not _job_is_running(job.id):
                break
            if job.max_comments and comment_counter[0] >= job.max_comments:
                break

            account = rotator.current()
            block_reason = get_account_runtime_block_reason(account)
            if block_reason:
                _log(
                    job,
                    level=NeuroCommentLog.Level.WARNING,
                    account=account,
                    message=f"{account.label}: пропущено: {block_reason}",
                )
                rotator.skip_current()
                consecutive_blocked += 1
                if consecutive_blocked >= len(rotator.accounts):
                    _log(
                        job,
                        level=NeuroCommentLog.Level.ERROR,
                        message="Усі акаунти заблоковані — зупиняємо задачу",
                    )
                    return
                continue
            consecutive_blocked = 0

            if job.ai_protection:
                recent = _account_recent_comment_count(
                    job.id, account.id, AI_PROTECTION_BURST_WINDOW_MIN
                )
                if recent >= AI_PROTECTION_BURST_LIMIT:
                    _log(
                        job,
                        level=NeuroCommentLog.Level.INFO,
                        account=account,
                        message=(
                            f"{account.label}: ліміт сплеску {AI_PROTECTION_BURST_LIMIT}/"
                            f"{AI_PROTECTION_BURST_WINDOW_MIN}хв — пропускаємо до охолодження"
                        ),
                    )
                    rotator.skip_current()
                    continue

            channel_key = str(_normalize_source(source)).lstrip("@")
            processed = processed_by_channel.setdefault(channel_key, set())

            try:
                done, exhausted = run_client_operation(
                    account,
                    lambda app, s=source, a=account, pids=processed: _process_source_existing_chunk(
                        app, job, a, s, prompts, comment_counter, pids, max_chunk
                    ),
                )
            except (FloodWait, RPCError) as exc:
                _handle_account_exception(job, account, exc, channel_username=channel_key)
                continue
            except Exception as exc:
                _handle_account_exception(job, account, exc, channel_username=channel_key)
                continue

            done = int(done or 0)
            for _ in range(done):
                rotator.mark_comment()
            round_progress += done
            if exhausted:
                exhausted_channels.add(channel_key)

        if round_progress == 0:
            # no channel produced a comment this round and none are claimed exhausted → bail
            break


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
    # Flip status first so any in-flight worker loop sees RUNNING == False on its next checkpoint.
    job.status = NeuroCommentJob.Status.STOPPED
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "finished_at", "updated_at"])
    if job.celery_task_id:
        # terminate=True forces the worker to drop the task; SIGTERM lets Celery clean up the child.
        AsyncResult(job.celery_task_id).revoke(terminate=True, signal="SIGTERM")
    _log(job, level=NeuroCommentLog.Level.SUCCESS, message="Задачу зупинено")
    return job


def run_neuro_comment_job(job_id: int) -> NeuroCommentJob:
    job = NeuroCommentJob.objects.prefetch_related("accounts", "selected_prompts").get(pk=job_id)
    accounts = list(
        job.accounts.filter(is_attached=True, auth_state=TelegramAccount.AuthState.CONNECTED)
    )
    if not accounts:
        raise RuntimeError("Немає валідних акаунтів для коментування.")

    raw_sources = [str(s).strip() for s in (job.sources or []) if str(s).strip()]
    if not raw_sources:
        raise RuntimeError("Немає джерел (каналів) для коментування.")

    # Split direct channels from t.me/addlist folder links. Folders are imported via one
    # CheckChatlistInvite + JoinChatlistInvite call per account, which Telegram registers
    # as a single "accepted the folder" action — far safer than N individual joins.
    direct_sources = [s for s in raw_sources if not _is_addlist_source(s)]
    addlist_sources = [s for s in raw_sources if _is_addlist_source(s)]

    if addlist_sources:
        _log(
            job,
            level=NeuroCommentLog.Level.INFO,
            message=f"Виявлено папок addlist: {len(addlist_sources)} — розгортаю...",
        )
        resolved_from_folders = _resolve_folder_sources(job, accounts, addlist_sources)
        # merge while keeping direct sources first so the user's explicit list wins ordering
        seen: set[str] = {s.lower() for s in direct_sources}
        for ref in resolved_from_folders:
            if ref.lower() in seen:
                continue
            seen.add(ref.lower())
            direct_sources.append(ref)

    sources = direct_sources
    if not sources:
        raise RuntimeError("Після обробки папок не лишилось каналів для коментування.")

    prompts = list(job.selected_prompts.all())
    comment_counter: list[int] = [0]

    deadline: float | None = None
    if job.work_mode == NeuroCommentJob.WorkMode.MONITORING:
        if job.duration_minutes:
            deadline = time.monotonic() + job.duration_minutes * 60
        elif not job.max_comments:
            # Safeguard: monitoring with no time limit AND no comment limit is a footgun —
            # without it the loop would run forever and never rotate past the first channel
            # batch into a graceful finish. Fall back to a sane default and warn the user.
            _log(
                job,
                level=NeuroCommentLog.Level.WARNING,
                message=(
                    f"Моніторинг без лімітів часу/кількості — використано стандартний ліміт "
                    f"{DEFAULT_MONITORING_FALLBACK_MINUTES} хв. Вкажіть тривалість або max_comments у задачі."
                ),
            )
            deadline = time.monotonic() + DEFAULT_MONITORING_FALLBACK_MINUTES * 60

    rotator = AccountRotator(
        accounts, every_n=job.rotation_every_n if job.account_rotation else None
    )

    try:
        if job.work_mode == NeuroCommentJob.WorkMode.MONITORING:
            _run_monitoring(job, rotator, sources, prompts, comment_counter, deadline)
        else:
            _run_by_count(job, rotator, sources, prompts, comment_counter)

        job.refresh_from_db()
        if job.status == NeuroCommentJob.Status.RUNNING:
            job.status = NeuroCommentJob.Status.SUCCEEDED
            job.finished_at = timezone.now()
            job.error = ""
            job.save(update_fields=["status", "finished_at", "error", "updated_at"])
            _log(
                job,
                level=NeuroCommentLog.Level.SUCCESS,
                message=f"Готово. Надіслано коментарів: {comment_counter[0]}",
            )
    except Exception as exc:
        job.refresh_from_db()
        # If the user already stopped the job, don't overwrite the STOPPED status with FAILED.
        if job.status == NeuroCommentJob.Status.RUNNING:
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
