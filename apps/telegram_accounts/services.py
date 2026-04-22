from __future__ import annotations

import asyncio
import random
import shutil
import socket
import time
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from threading import RLock
from uuid import uuid4

from django.conf import settings
from django.core.files.base import File
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from pyrogram import Client
from pyrogram.errors import BadRequest, RPCError, SessionPasswordNeeded
from pyrogram.methods.auth.connect import Connect
from pyrogram.methods.auth.disconnect import Disconnect

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

DEVICE_PROFILES = (
    ("iPhone 13 Pro", "iOS 17.4"),
    ("Samsung Galaxy S23", "Android 14"),
    ("Xiaomi 13", "Android 13"),
    ("MacBook Pro", "macOS 14.4"),
    ("Telegram Desktop", "Windows 11"),
)


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
    if device_model or system_version or not randomize_device_profile:
        return device_model, system_version
    return random.choice(DEVICE_PROFILES)


def remove_account_session_files(session_name: str) -> None:
    if not session_name:
        return
    workdir = telegram_runtime_workdir()
    for path in workdir.glob(f"{session_name}.session*"):
        try:
            path.unlink()
        except OSError:
            continue


def install_uploaded_session_file(account: TelegramAccount) -> None:
    if not account.session_file:
        return
    source = Path(account.session_file.path)
    destination = telegram_runtime_workdir() / f"{account.session_name}.session"
    shutil.copyfile(source, destination)


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


def build_account_client(account: TelegramAccount) -> Client:
    if not settings.TELEGRAM_API_ID or not settings.TELEGRAM_API_HASH:
        raise RuntimeError("TELEGRAM_API_ID or TELEGRAM_API_HASH is not configured.")
    return Client(
        name=account.session_name,
        api_id=settings.TELEGRAM_API_ID,
        api_hash=settings.TELEGRAM_API_HASH,
        workdir=telegram_runtime_workdir(),
        proxy=build_pyrogram_proxy(account.proxy),
        device_model=account.device_model or "Telegram AI Combine",
        system_version=account.system_version or "Local Runtime",
        no_updates=True,
    )


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
    with ensure_thread_event_loop():
        loop = asyncio.get_event_loop()
        app = build_account_client(account)
        loop.run_until_complete(Connect.connect(app))
        try:
            return loop.run_until_complete(operation(app))
        finally:
            if app.is_connected:
                loop.run_until_complete(Disconnect.disconnect(app))


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


def calculate_account_health_score(account: TelegramAccount) -> int:
    events = account.health_events.all()
    score = 100 + sum(event.score_delta for event in events)

    if account.last_error_at is None or account.last_error_at <= timezone.now() - timedelta(hours=1):
        score += 10

    return max(0, min(100, score))


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
    install_uploaded_session_file(account)
    try:
        async def verify_session_operation(app):
            if not await app.storage.user_id():
                raise RuntimeError("Uploaded session is not authorized.")
            return await app.get_me()

        user = run_client_operation(account, verify_session_operation)
        account.auth_state = TelegramAccount.AuthState.CONNECTED
        account.status = TelegramAccount.Status.ACTIVE
        account.last_auth_error = ""
        account.last_success_at = timezone.now()
        account.health_score = calculate_account_health_score(account)
        if user is not None:
            account.telegram_user_id = getattr(user, "id", None)
            account.telegram_username = getattr(user, "username", "") or ""
            account.first_name = getattr(user, "first_name", "") or ""
            account.last_name = getattr(user, "last_name", "") or ""
        account.save(
            update_fields=[
                "auth_state",
                "status",
                "last_auth_error",
                "last_success_at",
                "health_score",
                "telegram_user_id",
                "telegram_username",
                "first_name",
                "last_name",
            ]
        )
    except (BadRequest, RPCError, OSError, RuntimeError) as exc:
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
    old_session_name = account.session_name
    account.session_name = build_session_name(account.label, account.phone_number)
    account.auth_phone_code_hash = ""
    account.auth_code_sent_at = None
    account.auth_code_timeout_seconds = None
    account.auth_state = TelegramAccount.AuthState.PENDING_CODE
    account.last_auth_error = ""
    account.save(
        update_fields=[
            "session_name",
            "auth_phone_code_hash",
            "auth_code_sent_at",
            "auth_code_timeout_seconds",
            "auth_state",
            "last_auth_error",
        ]
    )
    remove_account_session_files(old_session_name)

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
                        account.requires_2fa = True
                        account.auth_state = TelegramAccount.AuthState.PENDING_2FA
                        account.last_auth_error = "2FA password required."
                        account.save(update_fields=["requires_2fa", "auth_state", "last_auth_error"])
                        return account
                    user = await app.check_password(password_2fa)
            elif account.auth_state == TelegramAccount.AuthState.PENDING_2FA:
                if not password_2fa:
                    account.last_auth_error = "2FA password required."
                    account.save(update_fields=["last_auth_error"])
                    return account
                user = await app.check_password(password_2fa)
            return user

        user = run_auth_flow_operation(account, complete_auth_operation)
        if isinstance(user, TelegramAccount):
            return user

        account.auth_phone_code_hash = ""
        account.auth_code_sent_at = None
        account.auth_code_timeout_seconds = None
        account.auth_state = TelegramAccount.AuthState.CONNECTED
        account.status = TelegramAccount.Status.ACTIVE
        account.last_auth_error = ""
        account.last_success_at = timezone.now()
        account.health_score = calculate_account_health_score(account)
        if user is not None:
            account.telegram_user_id = getattr(user, "id", None)
            account.telegram_username = getattr(user, "username", "") or ""
            account.first_name = getattr(user, "first_name", "") or ""
            account.last_name = getattr(user, "last_name", "") or ""
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
                "telegram_user_id",
                "telegram_username",
                "first_name",
                "last_name",
            ]
        )
        close_auth_flow(account.id)
    except (BadRequest, RPCError, OSError, RuntimeError) as exc:
        account.last_auth_error = telegram_error_text(exc)
        if telegram_error_contains(exc, "PHONE_CODE_INVALID") or telegram_error_contains(exc, "PHONE_CODE_EMPTY"):
            account.auth_state = TelegramAccount.AuthState.PENDING_CODE
        elif telegram_error_contains(exc, "PASSWORD_HASH_INVALID"):
            account.auth_state = TelegramAccount.AuthState.PENDING_2FA
        else:
            account.auth_state = TelegramAccount.AuthState.FAILED
            close_auth_flow(account.id)
        account.save(update_fields=["auth_state", "last_auth_error"])
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
    accounts = list(queryset.only("id", "session_name", "session_file"))
    for account in accounts:
        close_auth_flow(account.id)
        remove_account_session_files(account.session_name)
        if account.session_file:
            account.session_file.delete(save=False)
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
