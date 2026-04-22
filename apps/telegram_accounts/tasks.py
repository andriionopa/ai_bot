from celery import shared_task

from apps.telegram_accounts.models import AccountHealthEvent, Proxy, TelegramAccount
from apps.telegram_accounts.services import (
    check_proxy_connectivity,
    recalculate_account_state,
    register_account_runtime_event,
    release_expired_quarantine,
)
from apps.realtime.logging import publish_log_event


@shared_task
def ping_proxy_task(proxy_id: int) -> dict[str, object]:
    proxy = Proxy.objects.get(pk=proxy_id)
    result = check_proxy_connectivity(proxy)
    publish_log_event(
        {
            "level": "info" if result.ok else "error",
            "source": "proxy-checker",
            "message": f"Proxy {proxy.name} checked via {result.transport}",
            "latency_ms": result.latency_ms,
            "error": result.error,
        }
    )
    return {
        "ok": result.ok,
        "latency_ms": result.latency_ms,
        "error": result.error,
        "transport": result.transport,
    }


@shared_task
def register_account_runtime_event_task(
    account_id: int,
    event_type: str,
    metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    account = TelegramAccount.objects.get(pk=account_id)
    event = register_account_runtime_event(account, event_type=event_type, metadata=metadata)
    publish_log_event(
        {
            "level": "warning" if event_type != AccountHealthEvent.EventType.SUCCESS else "info",
            "source": "account-health",
            "message": f"{account.label}: {event.get_event_type_display()}",
            "account_id": account.id,
            "event_type": event_type,
            "health_score": account.health_score,
            "status": account.status,
            "quarantine_until": account.quarantine_until.isoformat() if account.quarantine_until else None,
        }
    )
    return {
        "account_id": account.id,
        "event_type": event.event_type,
        "health_score": account.health_score,
        "status": account.status,
    }


@shared_task
def recalculate_account_health_task(account_id: int) -> dict[str, object]:
    account = TelegramAccount.objects.get(pk=account_id)
    account = recalculate_account_state(account)
    return {
        "account_id": account.id,
        "health_score": account.health_score,
        "status": account.status,
    }


@shared_task
def recalculate_all_accounts_health_task() -> int:
    count = 0
    for account in TelegramAccount.objects.all():
        recalculate_account_state(account)
        count += 1
    return count


@shared_task
def release_expired_quarantines_task() -> int:
    released = 0
    for account in TelegramAccount.objects.filter(status=TelegramAccount.Status.QUARANTINE):
        if release_expired_quarantine(account):
            released += 1
    return released
