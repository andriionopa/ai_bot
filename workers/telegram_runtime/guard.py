from __future__ import annotations

from collections.abc import Callable

from pyrogram.errors import FloodWait, PeerFlood, UserDeactivatedBan

from apps.telegram_accounts.models import AccountHealthEvent


class AccountRuntimeBlocked(RuntimeError):
    pass


def classify_runtime_exception(exc: Exception) -> tuple[str, dict[str, object]] | None:
    if isinstance(exc, FloodWait):
        seconds = getattr(exc, "value", None) or getattr(exc, "x", None) or 0
        return AccountHealthEvent.EventType.FLOOD_WAIT, {"seconds": int(seconds)}
    if isinstance(exc, (PeerFlood, UserDeactivatedBan)):
        return AccountHealthEvent.EventType.SPAM_BLOCK, {"error": exc.__class__.__name__}
    return None


def execute_with_account_guard(
    *,
    account_id: int,
    action: Callable[[], object],
    reporter: Callable[[int, str, dict[str, object]], object],
    block_reason_loader: Callable[[], str] | None = None,
) -> object:
    if block_reason_loader is not None:
        block_reason = block_reason_loader()
        if block_reason:
            raise AccountRuntimeBlocked(block_reason)

    try:
        result = action()
    except Exception as exc:
        classified = classify_runtime_exception(exc)
        if classified is not None:
            event_type, metadata = classified
            reporter(account_id, event_type, metadata)
        raise

    reporter(account_id, AccountHealthEvent.EventType.SUCCESS, {"source": "worker"})
    return result


async def execute_async_with_account_guard(
    *,
    account_id: int,
    action: Callable[[], object],
    reporter: Callable[[int, str, dict[str, object]], object],
    block_reason_loader: Callable[[], str] | None = None,
) -> object:
    if block_reason_loader is not None:
        block_reason = block_reason_loader()
        if block_reason:
            raise AccountRuntimeBlocked(block_reason)

    try:
        result = await action()
    except Exception as exc:
        classified = classify_runtime_exception(exc)
        if classified is not None:
            event_type, metadata = classified
            reporter(account_id, event_type, metadata)
        raise

    reporter(account_id, AccountHealthEvent.EventType.SUCCESS, {"source": "worker"})
    return result
