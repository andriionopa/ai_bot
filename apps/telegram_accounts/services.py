from __future__ import annotations

import asyncio
import random
import shutil
import socket
import sqlite3
import time
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from threading import RLock
from uuid import uuid4

import redis
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from pyrogram import Client
from pyrogram.errors import BadRequest, RPCError, SessionPasswordNeeded
from pyrogram.methods.auth.connect import Connect
from pyrogram.methods.auth.disconnect import Disconnect
from pyrogram.storage.sqlite_storage import SCHEMA as PYROGRAM_SQLITE_SCHEMA
from pyrogram.storage.sqlite_storage import SQLiteStorage

from apps.telegram_accounts.models import AccountHealthEvent, Proxy, TelegramAccount


@dataclass
class ProxyCheckResult:
    ok: bool
    latency_ms: int | None
    error: str
    transport: str = "tcp"


@dataclass
class TelegramAuthFlow:
    account_id: int
    session_name: str
    proxy_id: int | None
    client: Client
    loop: asyncio.AbstractEventLoop
    expires_at: datetime
    lock: RLock


AUTH_FLOW_TTL = timedelta(minutes=5)
_AUTH_FLOWS: dict[int, TelegramAuthFlow] = {}
_AUTH_FLOWS_LOCK = RLock()


def check_proxy_connectivity(proxy: Proxy, timeout: float = 5.0) -> ProxyCheckResult:
    started = time.perf_counter()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((proxy.host, proxy.port))
    except OSError as exc:
        proxy.status = Proxy.Status.FAILED
        proxy.last_error = str(exc)
        proxy.last_checked_at = timezone.now()
        proxy.last_latency_ms = None
        proxy.save(update_fields=["status", "last_error", "last_checked_at", "last_latency_ms"])
        return ProxyCheckResult(ok=False, latency_ms=None, error=str(exc))
    finally:
        sock.close()

    latency_ms = int((time.perf_counter() - started) * 1000)
    proxy.status = Proxy.Status.HEALTHY
    proxy.last_error = ""
    proxy.last_checked_at = timezone.now()
    proxy.last_latency_ms = latency_ms
    proxy.save(update_fields=["status", "last_error", "last_checked_at", "last_latency_ms"])
    return ProxyCheckResult(ok=True, latency_ms=latency_ms, error="")


EVENT_SCORE_DELTAS = {
    AccountHealthEvent.EventType.FLOOD_WAIT: -15,
    AccountHealthEvent.EventType.SPAM_BLOCK: -30,
    AccountHealthEvent.EventType.SUCCESS: 2,
}

DEFAULT_DEVICE_MODEL = "iPhone 14 Pro"
DEFAULT_SYSTEM_VERSION = "iOS 17.2"
DEVICE_PROFILE_POOL = (
    # iPhone
    ("iPhone 16 Pro",        "iOS 18.1"),
    ("iPhone 16",            "iOS 18.0.1"),
    ("iPhone 15 Pro Max",    "iOS 17.6.1"),
    ("iPhone 15 Pro",        "iOS 17.5.1"),
    ("iPhone 15",            "iOS 17.4.1"),
    ("iPhone 14 Pro Max",    "iOS 17.3.1"),
    ("iPhone 14 Pro",        "iOS 17.2.1"),
    ("iPhone 14",            "iOS 17.1.2"),
    ("iPhone 13 Pro Max",    "iOS 16.7.4"),
    ("iPhone 13",            "iOS 16.6.1"),
    # Android flagship
    ("Samsung Galaxy S24 Ultra", "Android 14"),
    ("Samsung Galaxy S24",       "Android 14"),
    ("Samsung Galaxy S23 Ultra", "Android 14"),
    ("Samsung Galaxy S23",       "Android 13"),
    ("Google Pixel 8 Pro",       "Android 14"),
    ("Google Pixel 8",           "Android 14"),
    ("Google Pixel 7a",          "Android 14"),
    ("OnePlus 12",               "Android 14"),
    ("Xiaomi 14",                "Android 14"),
    ("Xiaomi 13T Pro",           "Android 13"),
    # Android mid-range
    ("Samsung Galaxy A54",   "Android 13"),
    ("Samsung Galaxy A34",   "Android 13"),
    ("Xiaomi Redmi Note 13", "Android 13"),
    ("POCO X6 Pro",          "Android 14"),
    ("Motorola Edge 40",     "Android 13"),
)
RISKY_DEVICE_MODELS = {
    "web automation",
    "automation",
    "bot",
    "script",
    "python",
    "telethon",
    "pyrogram",
    "pc 64bit",
}


def build_session_name(label: str, phone_number: str = "") -> str:
    seed = slugify(label) or "account"
    suffix = slugify(phone_number) or uuid4().hex[:8]
    return f"{seed}-{suffix}-{uuid4().hex[:6]}"


def resolve_device_profile(
    *,
    device_model: str = "",
    system_version: str = "",
    randomize_device_profile: bool = True,
) -> tuple[str, str]:
    device_model = (device_model or "").strip()
    system_version = (system_version or "").strip()
    if randomize_device_profile and (not device_model or not system_version):
        picked_device, picked_system = random.choice(DEVICE_PROFILE_POOL)
        device_model = device_model or picked_device
        system_version = system_version or picked_system
    if not device_model or device_model.lower() in RISKY_DEVICE_MODELS:
        device_model = DEFAULT_DEVICE_MODEL
    if not system_version:
        system_version = DEFAULT_SYSTEM_VERSION
    return device_model, system_version


def remove_account_session_files(session_name: str) -> None:
    if not session_name:
        return
    workdir = telegram_runtime_workdir()
    for path in workdir.glob(f"{session_name}.session*"):
        try:
            path.unlink()
        except OSError:
            continue


@transaction.atomic
def delete_account_with_files(account: TelegramAccount) -> None:
    close_auth_flow(account.id)
    remove_account_session_files(account.session_name)
    if account.session_file:
        account.session_file.delete(save=False)
    for draft in account.profile_drafts.exclude(photo="").only("id", "photo"):
        draft.photo.delete(save=False)
    account.delete()


def install_uploaded_session_file(account: TelegramAccount) -> None:
    if not account.session_file:
        return
    source = Path(account.session_file.path)
    destination = telegram_runtime_workdir() / f"{account.session_name}.session"
    if is_telethon_session_file(source):
        convert_telethon_session_to_pyrogram(source, destination)
        return
    shutil.copyfile(source, destination)


def sqlite_table_columns(path: Path, table: str) -> set[str]:
    with sqlite3.connect(path) as conn:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def is_telethon_session_file(path: Path) -> bool:
    try:
        session_columns = sqlite_table_columns(path, "sessions")
        version_columns = sqlite_table_columns(path, "version")
    except sqlite3.DatabaseError:
        return False
    return "version" in version_columns and {"dc_id", "server_address", "port", "auth_key"}.issubset(session_columns)


def convert_telethon_session_to_pyrogram(source: Path, destination: Path) -> None:
    with sqlite3.connect(source) as source_conn:
        row = source_conn.execute(
            "SELECT dc_id, auth_key FROM sessions WHERE auth_key IS NOT NULL ORDER BY dc_id LIMIT 1"
        ).fetchone()
    if not row:
        raise RuntimeError("Telethon session is not authorized or does not contain an auth key.")

    dc_id, auth_key = row
    if destination.exists():
        destination.unlink()
    with sqlite3.connect(destination) as destination_conn:
        destination_conn.executescript(PYROGRAM_SQLITE_SCHEMA)
        destination_conn.execute("INSERT INTO version VALUES (?)", (SQLiteStorage.VERSION,))
        destination_conn.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?)",
            (dc_id, settings.TELEGRAM_API_ID, 0, auth_key, int(time.time()), None, None),
        )
        destination_conn.commit()


def build_pyrogram_proxy(proxy: Proxy | None) -> dict[str, object] | None:
    if proxy is None:
        return None
    return {
        "scheme": proxy.protocol,
        "hostname": proxy.host,
        "port": proxy.port,
        "username": proxy.username or None,
        "password": proxy.password or None,
    }


def telegram_runtime_workdir() -> Path:
    workdir = Path(settings.MEDIA_ROOT) / "telegram_runtime"
    workdir.mkdir(parents=True, exist_ok=True)
    return workdir


def _app_version_for_device(device_model: str) -> str:
    """Return a plausible Telegram app version matching the device type."""
    d = device_model.lower()
    if "iphone" in d or "ios" in d:
        return "10.14.5"   # Telegram iOS
    if "samsung" in d or "pixel" in d or "xiaomi" in d or "android" in d or "poco" in d or "oneplus" in d or "motorola" in d:
        return "10.14.5"   # Telegram Android
    return "4.16.8"        # Telegram Desktop fallback


def _lang_for_geo(phone_number: str) -> str:
    """Return a plausible lang_code based on phone prefix."""
    digits = (phone_number or "").lstrip("+").lstrip("0")
    if digits.startswith("380"):
        return "uk"
    if digits.startswith("7") or digits.startswith("375"):
        return "ru"
    if digits.startswith("48"):
        return "pl"
    return "en"


def build_account_client(account: TelegramAccount) -> Client:
    if not settings.TELEGRAM_API_ID or not settings.TELEGRAM_API_HASH:
        raise RuntimeError("TELEGRAM_API_ID or TELEGRAM_API_HASH is not configured.")
    device_model, system_version = resolve_device_profile(
        device_model=account.device_model,
        system_version=account.system_version,
        randomize_device_profile=account.randomize_device_profile,
    )
    # Persist chosen profile so device stays consistent across connections
    if device_model != account.device_model or system_version != account.system_version:
        TelegramAccount.objects.filter(pk=account.pk).update(
            device_model=device_model,
            system_version=system_version,
        )
        account.device_model = device_model
        account.system_version = system_version

    return Client(
        name=account.session_name,
        api_id=settings.TELEGRAM_API_ID,
        api_hash=settings.TELEGRAM_API_HASH,
        workdir=telegram_runtime_workdir(),
        proxy=build_pyrogram_proxy(account.proxy),
        device_model=device_model,
        system_version=system_version,
        app_version=_app_version_for_device(device_model),
        lang_code=_lang_for_geo(account.phone_number),
        no_updates=True,
    )


@contextmanager
def account_session_lock(account: TelegramAccount, *, timeout: int = 600, blocking_timeout: int = 180):
    client = redis.from_url(settings.CELERY_BROKER_URL)
    lock = client.lock(
        f"telegram-account-session:{account.session_name}",
        timeout=timeout,
        blocking_timeout=blocking_timeout,
    )
    acquired = lock.acquire(blocking=True)
    if not acquired:
        raise RuntimeError(
            f"Telegram session is busy for account {account.label}; "
            "previous operation did not release the session lock in time."
        )
    try:
        yield
    finally:
        try:
            lock.release()
        except redis.exceptions.LockError:
            pass


@contextmanager
def ensure_thread_event_loop():
    created = False
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        created = True

    try:
        yield loop
    finally:
        if created:
            loop.close()
            asyncio.set_event_loop(None)


def run_client_operation(account: TelegramAccount, operation):
    with account_session_lock(account), ensure_thread_event_loop():
        loop = asyncio.get_event_loop()
        app = build_account_client(account)
        loop.run_until_complete(Connect.connect(app))
        try:
            pause_min = max(0, int(account.sleep_min_seconds or 0))
            pause_max = max(pause_min, int(account.sleep_max_seconds or pause_min))
            if pause_max:
                loop.run_until_complete(asyncio.sleep(random.randint(pause_min, pause_max)))
            return loop.run_until_complete(operation(app))
        finally:
            if app.is_connected:
                loop.run_until_complete(Disconnect.disconnect(app))


def refresh_account_profile_snapshot(account: TelegramAccount) -> TelegramAccount:
    async def snapshot_operation(app):
        return await app.get_me()

    user = run_client_operation(account, snapshot_operation)
    update_fields = [
        "telegram_user_id",
        "telegram_username",
        "first_name",
        "last_name",
        "last_success_at",
    ]
    account.telegram_user_id = getattr(user, "id", None)
    account.telegram_username = getattr(user, "username", "") or ""
    account.first_name = getattr(user, "first_name", "") or ""
    account.last_name = getattr(user, "last_name", "") or ""
    account.last_success_at = timezone.now()

    account.save(update_fields=update_fields)
    return account


def check_account_spam_block(account: TelegramAccount) -> dict[str, object]:
    async def spam_check_operation(app):
        await app.send_message("SpamBot", "/start")
        await asyncio.sleep(2)
        messages: list[str] = []
        async for message in app.get_chat_history("SpamBot", limit=3):
            text = (getattr(message, "text", "") or getattr(message, "caption", "") or "").strip()
            if text:
                messages.append(text)
        joined = " ".join(messages).lower()
        limited = any(
            marker in joined
            for marker in (
                "limited",
                "restriction",
                "restricted",
                "spam",
                "can't send",
                "cannot send",
                "обмеж",
                "спам",
            )
        )
        return {"limited": limited, "messages": messages}

    return run_client_operation(account, spam_check_operation)


def _enum_value(value) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "").lower()


def _isoformat(value) -> str | None:
    return value.isoformat() if value else None


def _chat_display_title(chat) -> str:
    title = getattr(chat, "title", "") or ""
    if title:
        return title
    full_name = " ".join(
        part
        for part in (
            getattr(chat, "first_name", "") or "",
            getattr(chat, "last_name", "") or "",
        )
        if part
    ).strip()
    return full_name or getattr(chat, "username", "") or str(getattr(chat, "id", ""))


def _message_text(message) -> str:
    text = getattr(message, "text", "") or getattr(message, "caption", "") or ""
    if text:
        return text
    if getattr(message, "media", None):
        return "[media]"
    if getattr(message, "service", None):
        return "[service]"
    return ""


def _serialize_chat(chat) -> dict[str, object]:
    return {
        "id": str(getattr(chat, "id", "")),
        "title": _chat_display_title(chat),
        "username": getattr(chat, "username", "") or "",
        "type": _enum_value(getattr(chat, "type", "")),
    }


def _serialize_message(message) -> dict[str, object]:
    sender = getattr(message, "from_user", None) or getattr(message, "sender_chat", None)
    return {
        "id": getattr(message, "id", None),
        "date": _isoformat(getattr(message, "date", None)),
        "outgoing": bool(getattr(message, "outgoing", False)),
        "text": _message_text(message),
        "sender": _chat_display_title(sender) if sender else "",
        "sender_username": getattr(sender, "username", "") or "",
        "media": bool(getattr(message, "media", None)),
    }


def parse_telegram_chat_id(value: str):
    text = str(value or "").strip()
    if not text:
        raise ValueError("chat_id is required.")
    return int(text) if text.lstrip("-").isdigit() else text


async def ensure_dialog_peer_cached(app, chat_id) -> bool:
    if not isinstance(chat_id, int):
        return True
    async for dialog in app.get_dialogs(limit=200):
        chat = getattr(dialog, "chat", None)
        if getattr(chat, "id", None) == chat_id:
            return True
    return False


def list_account_dialogs(account: TelegramAccount, *, limit: int = 40) -> list[dict[str, object]]:
    async def dialogs_operation(app):
        dialogs: list[dict[str, object]] = []
        async for dialog in app.get_dialogs(limit=limit):
            chat = getattr(dialog, "chat", None)
            if chat is None:
                continue
            top_message = getattr(dialog, "top_message", None)
            item = _serialize_chat(chat)
            item.update(
                {
                    "unread_count": getattr(dialog, "unread_messages_count", 0) or 0,
                    "last_message": _message_text(top_message) if top_message else "",
                    "last_message_date": _isoformat(getattr(top_message, "date", None)) if top_message else None,
                }
            )
            dialogs.append(item)
        return dialogs

    return run_client_operation(account, dialogs_operation)


def list_account_chat_messages(
    account: TelegramAccount,
    *,
    chat_id: str,
    limit: int = 50,
) -> dict[str, object]:
    parsed_chat_id = parse_telegram_chat_id(chat_id)

    async def messages_operation(app):
        if not await ensure_dialog_peer_cached(app, parsed_chat_id):
            raise RuntimeError("Telegram не знайшов цей діалог у списку доступних чатів поточного акаунта.")
        chat = await app.get_chat(parsed_chat_id)
        messages = []
        async for message in app.get_chat_history(parsed_chat_id, limit=limit):
            messages.append(_serialize_message(message))
        messages.reverse()
        return {
            "chat": _serialize_chat(chat),
            "messages": messages,
        }

    return run_client_operation(account, messages_operation)


def send_account_chat_message(
    account: TelegramAccount,
    *,
    chat_id: str,
    text: str,
) -> dict[str, object]:
    parsed_chat_id = parse_telegram_chat_id(chat_id)

    async def send_operation(app):
        if not await ensure_dialog_peer_cached(app, parsed_chat_id):
            raise RuntimeError("Telegram не знайшов цей діалог у списку доступних чатів поточного акаунта.")
        message = await app.send_message(chat_id=parsed_chat_id, text=text)
        return _serialize_message(message)

    result = run_client_operation(account, send_operation)
    account.last_success_at = timezone.now()
    account.last_auth_error = ""
    account.save(update_fields=["last_success_at", "last_auth_error"])
    return result


def check_account_proxy_connectivity(account: TelegramAccount) -> dict[str, object]:
    if account.proxy is None:
        return {"ok": False, "latency_ms": None, "error": "Акаунт не має призначеного проксі."}
    result = check_proxy_connectivity(account.proxy)
    return {
        "ok": result.ok,
        "latency_ms": result.latency_ms,
        "error": result.error,
        "proxy_id": account.proxy_id,
        "proxy_name": account.proxy.name,
    }


def create_account_channel(
    account: TelegramAccount,
    *,
    title: str,
    description: str = "",
    supergroup: bool = False,
) -> dict[str, object]:
    async def create_channel_operation(app):
        chat = (
            await app.create_supergroup(title, description)
            if supergroup
            else await app.create_channel(title, description)
        )
        return {
            "id": getattr(chat, "id", None),
            "title": getattr(chat, "title", title),
            "username": getattr(chat, "username", "") or "",
            "type": str(getattr(chat, "type", "")),
        }

    return run_client_operation(account, create_channel_operation)


def set_account_cloud_password(
    account: TelegramAccount,
    *,
    new_password: str,
    current_password: str = "",
    hint: str = "",
    email: str = "",
) -> dict[str, object]:
    async def set_password_operation(app):
        if current_password:
            result = await app.change_cloud_password(current_password, new_password, hint)
        else:
            result = await app.enable_cloud_password(new_password, hint, email or None)
        return {"enabled": bool(result)}

    result = run_client_operation(account, set_password_operation)
    account.requires_2fa = True
    account.last_success_at = timezone.now()
    account.last_auth_error = ""
    account.save(update_fields=["requires_2fa", "last_success_at", "last_auth_error"])
    return result


def _flow_expired(flow: TelegramAuthFlow) -> bool:
    return flow.expires_at <= timezone.now()


def close_auth_flow(account_id: int) -> None:
    with _AUTH_FLOWS_LOCK:
        flow = _AUTH_FLOWS.pop(account_id, None)
    if flow is None:
        return

    with flow.lock:
        try:
            if flow.client.is_connected:
                flow.loop.run_until_complete(Disconnect.disconnect(flow.client))
        finally:
            flow.loop.close()


def _get_auth_flow(account: TelegramAccount, *, reset: bool = False) -> TelegramAuthFlow:
    with _AUTH_FLOWS_LOCK:
        flow = _AUTH_FLOWS.get(account.id)

    if (
        reset
        or flow is None
        or flow.session_name != account.session_name
        or flow.proxy_id != account.proxy_id
        or _flow_expired(flow)
    ):
        if flow is not None:
            close_auth_flow(account.id)

        loop = asyncio.new_event_loop()
        previous_loop = None
        try:
            previous_loop = asyncio.get_event_loop()
        except RuntimeError:
            previous_loop = None
        asyncio.set_event_loop(loop)
        client = build_account_client(account)
        flow = TelegramAuthFlow(
            account_id=account.id,
            session_name=account.session_name,
            proxy_id=account.proxy_id,
            client=client,
            loop=loop,
            expires_at=timezone.now() + AUTH_FLOW_TTL,
            lock=RLock(),
        )
        try:
            loop.run_until_complete(Connect.connect(client))
        finally:
            asyncio.set_event_loop(previous_loop)

        with _AUTH_FLOWS_LOCK:
            _AUTH_FLOWS[account.id] = flow

    return flow


def run_auth_flow_operation(account: TelegramAccount, operation, *, reset: bool = False):
    flow = _get_auth_flow(account, reset=reset)
    with flow.lock:
        flow.expires_at = timezone.now() + AUTH_FLOW_TTL
        previous_loop = None
        try:
            previous_loop = asyncio.get_event_loop()
        except RuntimeError:
            previous_loop = None
        asyncio.set_event_loop(flow.loop)
        try:
            return flow.loop.run_until_complete(operation(flow.client))
        finally:
            asyncio.set_event_loop(previous_loop)


def telegram_error_text(exc: Exception) -> str:
    return str(exc)


def telegram_error_contains(exc: Exception, code: str) -> bool:
    return code in telegram_error_text(exc)


def telegram_user_facing_error(exc: Exception) -> str:
    error_text = telegram_error_text(exc)
    upper_error = error_text.upper()
    if "CHAT_ADMIN_REQUIRED" in upper_error:
        return "У цей канал можна писати тільки з правами адміністратора. Видайте цьому Telegram-акаунту admin-права в каналі або оберіть чат/групу, де дозволені повідомлення."
    if "PEER_ID_INVALID" in upper_error or "PEER ID INVALID" in upper_error:
        return "Telegram не дав доступ до цього діалогу для поточної сесії. Оновіть список чатів, відкрийте діалог ще раз або переавторизуйте акаунт."
    if "FLOOD_WAIT" in upper_error:
        return "Telegram тимчасово обмежив дію для цього акаунта. Зачекайте FloodWait перед повторною спробою."
    return error_text


def calculate_account_health_score(account: TelegramAccount) -> int:
    events = account.health_events.all()
    score = 100 + sum(event.score_delta for event in events)

    if account.last_error_at is None or account.last_error_at <= timezone.now() - timedelta(hours=1):
        score += 10

    return max(0, min(100, score))


def account_liveness_score(account: TelegramAccount) -> int:
    score = account.health_score
    if account.is_quarantined:
        score -= 35
    elif account.status != TelegramAccount.Status.ACTIVE:
        score -= 15
    if account.last_error_at and account.last_error_at > timezone.now() - timedelta(hours=1):
        score -= 10
    if account.last_success_at and account.last_success_at > timezone.now() - timedelta(hours=6):
        score += 5
    return max(0, min(100, score))


def account_risk_level(account: TelegramAccount) -> str:
    liveness = account_liveness_score(account)
    if account.is_quarantined or liveness < 45:
        return "high"
    if liveness < 70 or account.health_score < 75:
        return "medium"
    return "low"


def _stop_account_warmup_actions_for_quarantine(account: TelegramAccount, *, reason: str, metadata: dict[str, object]) -> int:
    from apps.warmup.models import WarmupAction

    current_action_id = metadata.get("action_id")
    queryset = WarmupAction.objects.filter(
        account=account,
        status__in=[WarmupAction.Status.QUEUED, WarmupAction.Status.RUNNING],
        plan__status__in=["running"],
    )
    if current_action_id:
        queryset = queryset.exclude(pk=current_action_id)
    stopped = queryset.update(
        status=WarmupAction.Status.SKIPPED,
        error=reason,
        finished_at=timezone.now(),
        updated_at=timezone.now(),
    )
    return stopped


@transaction.atomic
def attach_account_via_session(
    *,
    owner,
    label: str,
    session_file: File,
    phone_number: str = "",
    proxy: Proxy | None = None,
    device_model: str = "",
    system_version: str = "",
    randomize_device_profile: bool = True,
) -> TelegramAccount:
    session_basename = Path(getattr(session_file, "name", "")).stem
    session_name = build_session_name(session_basename or label, phone_number)
    device_model, system_version = resolve_device_profile(
        device_model=device_model,
        system_version=system_version,
        randomize_device_profile=randomize_device_profile,
    )
    account = TelegramAccount.objects.create(
        owner=owner,
        label=label,
        phone_number=phone_number,
        session_name=session_name,
        source=TelegramAccount.ConnectSource.SESSION,
        auth_state=TelegramAccount.AuthState.SESSION_UPLOADED,
        status=TelegramAccount.Status.DRAFT,
        proxy=proxy,
        session_file=session_file,
        device_model=device_model,
        system_version=system_version,
        randomize_device_profile=randomize_device_profile,
        is_attached=True,
    )
    try:
        install_uploaded_session_file(account)

        async def verify_session_operation(app):
            return await app.get_me()

        user = run_client_operation(account, verify_session_operation)
        account.auth_state = TelegramAccount.AuthState.CONNECTED
        account.status = TelegramAccount.Status.ACTIVE
        account.last_auth_error = ""
        account.last_success_at = timezone.now()
        account.health_score = calculate_account_health_score(account)
        account.save(
            update_fields=[
                "auth_state",
                "status",
                "last_auth_error",
                "last_success_at",
                "health_score",
            ]
        )
        refresh_account_profile_snapshot(account)
    except (BadRequest, RPCError, OSError, RuntimeError, sqlite3.DatabaseError) as exc:
        remove_account_session_files(account.session_name)
        account.auth_state = TelegramAccount.AuthState.FAILED
        account.status = TelegramAccount.Status.DRAFT
        account.last_auth_error = telegram_error_text(exc)
        account.last_error_at = timezone.now()
        account.save(update_fields=["auth_state", "status", "last_auth_error", "last_error_at"])
    return account


@transaction.atomic
def start_credentials_auth(
    *,
    owner,
    label: str,
    phone_number: str,
    proxy: Proxy | None = None,
    requires_2fa: bool = False,
    device_model: str = "",
    system_version: str = "",
    randomize_device_profile: bool = True,
) -> TelegramAccount:
    device_model, system_version = resolve_device_profile(
        device_model=device_model,
        system_version=system_version,
        randomize_device_profile=randomize_device_profile,
    )
    account = TelegramAccount.objects.create(
        owner=owner,
        label=label,
        phone_number=phone_number,
        session_name=build_session_name(label, phone_number),
        source=TelegramAccount.ConnectSource.CREDENTIALS,
        auth_state=TelegramAccount.AuthState.PENDING_CODE,
        status=TelegramAccount.Status.DRAFT,
        proxy=proxy,
        requires_2fa=requires_2fa,
        auth_phone_code_hash="",
        device_model=device_model,
        system_version=system_version,
        randomize_device_profile=randomize_device_profile,
        is_attached=True,
    )
    try:
        async def send_code_operation(app):
            return await app.send_code(phone_number)

        sent_code = run_auth_flow_operation(account, send_code_operation, reset=True)
        account.auth_phone_code_hash = sent_code.phone_code_hash
        account.auth_code_sent_at = timezone.now()
        account.auth_code_timeout_seconds = getattr(sent_code, "timeout", None)
        account.auth_state = TelegramAccount.AuthState.PENDING_CODE
        account.last_auth_error = ""
        account.save(
            update_fields=[
                "auth_phone_code_hash",
                "auth_code_sent_at",
                "auth_code_timeout_seconds",
                "auth_state",
                "last_auth_error",
            ]
        )
    except (BadRequest, RPCError, OSError, RuntimeError) as exc:
        close_auth_flow(account.id)
        account.auth_state = TelegramAccount.AuthState.FAILED
        account.last_auth_error = telegram_error_text(exc)
        account.save(update_fields=["auth_state", "last_auth_error"])
    return account


@transaction.atomic
def resend_credentials_code(account: TelegramAccount) -> TelegramAccount:
    close_auth_flow(account.id)
    device_model, system_version = resolve_device_profile(
        device_model=account.device_model,
        system_version=account.system_version,
        randomize_device_profile=False,
    )
    account.device_model = device_model
    account.system_version = system_version
    account.source = TelegramAccount.ConnectSource.CREDENTIALS
    account.auth_phone_code_hash = ""
    account.auth_code_sent_at = None
    account.auth_code_timeout_seconds = None
    account.auth_state = TelegramAccount.AuthState.PENDING_CODE
    account.status = TelegramAccount.Status.DRAFT
    account.is_attached = True
    account.detached_at = None
    account.last_auth_error = ""
    account.save(
        update_fields=[
            "device_model",
            "system_version",
            "source",
            "auth_phone_code_hash",
            "auth_code_sent_at",
            "auth_code_timeout_seconds",
            "auth_state",
            "status",
            "is_attached",
            "detached_at",
            "last_auth_error",
        ]
    )
    remove_account_session_files(account.session_name)

    # Refresh proxy from DB so the new client uses the current proxy, not a stale in-memory value.
    account.refresh_from_db(fields=["proxy_id"])
    account.__dict__.pop("proxy", None)

    try:
        async def send_code_operation(app):
            return await app.send_code(account.phone_number)

        sent_code = run_auth_flow_operation(account, send_code_operation, reset=True)
        account.auth_phone_code_hash = sent_code.phone_code_hash
        account.auth_code_sent_at = timezone.now()
        account.auth_code_timeout_seconds = getattr(sent_code, "timeout", None)
        account.auth_state = TelegramAccount.AuthState.PENDING_CODE
        account.last_auth_error = ""
        account.save(
            update_fields=[
                "auth_phone_code_hash",
                "auth_code_sent_at",
                "auth_code_timeout_seconds",
                "auth_state",
                "last_auth_error",
            ]
        )
    except (BadRequest, RPCError, OSError, RuntimeError) as exc:
        close_auth_flow(account.id)
        account.auth_state = TelegramAccount.AuthState.FAILED
        account.last_auth_error = telegram_error_text(exc)
        account.save(update_fields=["auth_state", "last_auth_error"])
    return account


@transaction.atomic
def complete_credentials_auth(
    account: TelegramAccount,
    *,
    verification_code: str = "",
    password_2fa: str = "",
) -> TelegramAccount:
    if account.auth_state == TelegramAccount.AuthState.PENDING_CODE and not verification_code:
        account.last_auth_error = "Verification code required."
        account.save(update_fields=["last_auth_error"])
        return account

    try:
        async def complete_auth_operation(app):
            user = None
            if account.auth_state == TelegramAccount.AuthState.PENDING_CODE:
                try:
                    user = await app.sign_in(
                        account.phone_number,
                        account.auth_phone_code_hash,
                        verification_code,
                    )
                except SessionPasswordNeeded:
                    if not password_2fa:
                        return {
                            "auth_state": TelegramAccount.AuthState.PENDING_2FA,
                            "last_auth_error": "2FA password required.",
                            "requires_2fa": True,
                        }
                    user = await app.check_password(password_2fa)
            elif account.auth_state == TelegramAccount.AuthState.PENDING_2FA:
                if not password_2fa:
                    return {
                        "auth_state": TelegramAccount.AuthState.PENDING_2FA,
                        "last_auth_error": "2FA password required.",
                        "requires_2fa": True,
                    }
                user = await app.check_password(password_2fa)
            return user

        user = run_auth_flow_operation(account, complete_auth_operation)
        if isinstance(user, dict) and user.get("auth_state") == TelegramAccount.AuthState.PENDING_2FA:
            account.requires_2fa = bool(user.get("requires_2fa", True))
            account.auth_state = TelegramAccount.AuthState.PENDING_2FA
            account.last_auth_error = str(user.get("last_auth_error") or "2FA password required.")
            account.save(update_fields=["requires_2fa", "auth_state", "last_auth_error"])
            return account

        account.auth_phone_code_hash = ""
        account.auth_code_sent_at = None
        account.auth_code_timeout_seconds = None
        account.auth_state = TelegramAccount.AuthState.CONNECTED
        account.status = TelegramAccount.Status.ACTIVE
        account.last_auth_error = ""
        account.last_success_at = timezone.now()
        account.health_score = calculate_account_health_score(account)
        account.save(
            update_fields=[
                "auth_phone_code_hash",
                "auth_code_sent_at",
                "auth_code_timeout_seconds",
                "auth_state",
                "status",
                "last_auth_error",
                "last_success_at",
                "health_score",
            ]
        )
        refresh_account_profile_snapshot(account)
        close_auth_flow(account.id)
    except (BadRequest, RPCError, OSError, RuntimeError) as exc:
        account.last_auth_error = telegram_error_text(exc)
        if telegram_error_contains(exc, "PHONE_CODE_INVALID") or telegram_error_contains(exc, "PHONE_CODE_EMPTY"):
            account.auth_state = TelegramAccount.AuthState.PENDING_CODE
        elif (
            telegram_error_contains(exc, "PASSWORD_HASH_INVALID")
            or telegram_error_contains(exc, "SESSION_PASSWORD_NEEDED")
            or telegram_error_contains(exc, "PASSWORD_MISSING")
        ):
            account.requires_2fa = True
            account.auth_state = TelegramAccount.AuthState.PENDING_2FA
        else:
            account.auth_state = TelegramAccount.AuthState.FAILED
            close_auth_flow(account.id)
        account.save(update_fields=["auth_state", "requires_2fa", "last_auth_error"])
    return account


@transaction.atomic
def bulk_detach_accounts(*, owner, account_ids: Iterable[int]) -> int:
    ids = list(account_ids)
    if not ids:
        return 0
    now = timezone.now()
    updated = (
        TelegramAccount.objects.filter(owner=owner, pk__in=ids, is_attached=True)
        .update(
            is_attached=False,
            detached_at=now,
            auth_state=TelegramAccount.AuthState.DETACHED,
            status=TelegramAccount.Status.DRAFT,
            quarantine_until=None,
        )
    )
    for account_id in ids:
        close_auth_flow(account_id)
    return updated


@transaction.atomic
def cleanup_stale_accounts(*, owner) -> int:
    queryset = TelegramAccount.objects.filter(
        owner=owner,
        auth_state__in=[
            TelegramAccount.AuthState.FAILED,
            TelegramAccount.AuthState.DETACHED,
        ],
    )
    accounts = list(queryset.prefetch_related("profile_drafts").only("id", "session_name", "session_file"))
    for account in accounts:
        close_auth_flow(account.id)
        remove_account_session_files(account.session_name)
        if account.session_file:
            account.session_file.delete(save=False)
        for draft in account.profile_drafts.exclude(photo="").only("id", "photo"):
            draft.photo.delete(save=False)
    deleted, _ = queryset.delete()
    return deleted


@transaction.atomic
def register_account_runtime_event(
    account: TelegramAccount,
    event_type: str,
    metadata: dict[str, object] | None = None,
) -> AccountHealthEvent:
    now = timezone.now()
    metadata = metadata or {}
    score_delta = EVENT_SCORE_DELTAS[event_type]

    event = AccountHealthEvent.objects.create(
        account=account,
        event_type=event_type,
        score_delta=score_delta,
        metadata=metadata,
    )

    updates: dict[str, object] = {}
    if event_type == AccountHealthEvent.EventType.SUCCESS:
        updates["last_success_at"] = now
    else:
        updates["last_error_at"] = now

    if event_type == AccountHealthEvent.EventType.FLOOD_WAIT:
        updates["status"] = TelegramAccount.Status.QUARANTINE
        updates["quarantine_until"] = now + timedelta(hours=24)
    elif event_type == AccountHealthEvent.EventType.SPAM_BLOCK:
        updates["status"] = TelegramAccount.Status.QUARANTINE
        updates["quarantine_until"] = now + timedelta(hours=24)

    for field, value in updates.items():
        setattr(account, field, value)

    account.health_score = calculate_account_health_score(account)
    save_fields = ["health_score", *updates.keys()]
    account.save(update_fields=save_fields)
    if event_type in {AccountHealthEvent.EventType.FLOOD_WAIT, AccountHealthEvent.EventType.SPAM_BLOCK}:
        seconds = metadata.get("seconds")
        reason = (
            f"Account quarantined for 24h until {account.quarantine_until.isoformat()} "
            f"({event.get_event_type_display()}{f' {seconds} с' if seconds else ''})"
        )
        stopped_actions = _stop_account_warmup_actions_for_quarantine(account, reason=reason, metadata=metadata)
        metadata["stopped_warmup_actions"] = stopped_actions
        event.metadata = metadata
        event.save(update_fields=["metadata"])
    return event


def get_account_runtime_block_reason(account: TelegramAccount) -> str:
    if not account.is_attached:
        return "Account is detached from farm."
    if account.auth_state != TelegramAccount.AuthState.CONNECTED:
        return f"Account auth state is {account.auth_state}."
    if account.is_quarantined:
        return f"Account is quarantined until {account.quarantine_until.isoformat()}."
    if account.status in {TelegramAccount.Status.BANNED, TelegramAccount.Status.QUARANTINE}:
        return f"Account status is {account.status}."
    return ""


def release_expired_quarantine(account: TelegramAccount) -> bool:
    if (
        account.status == TelegramAccount.Status.QUARANTINE
        and account.quarantine_until
        and account.quarantine_until <= timezone.now()
    ):
        account.status = TelegramAccount.Status.ACTIVE
        account.quarantine_until = None
        account.health_score = calculate_account_health_score(account)
        account.save(update_fields=["status", "quarantine_until", "health_score"])
        return True
    return False


def recalculate_account_state(account: TelegramAccount) -> TelegramAccount:
    released = release_expired_quarantine(account)
    if not released:
        account.health_score = calculate_account_health_score(account)
        account.save(update_fields=["health_score"])
    return account


@transaction.atomic
def assign_account_proxy(account: TelegramAccount, proxy: Proxy | None) -> TelegramAccount:
    account.proxy = proxy
    account.save(update_fields=["proxy"])
    close_auth_flow(account.id)
    return account
