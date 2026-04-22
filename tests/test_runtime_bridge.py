import asyncio

import pytest
from pyrogram.errors import FloodWait, PeerFlood

from apps.telegram_accounts.models import AccountHealthEvent
from workers.telegram_runtime.guard import (
    AccountRuntimeBlocked,
    classify_runtime_exception,
    execute_async_with_account_guard,
    execute_with_account_guard,
)


def test_classify_runtime_exception_maps_flood_wait_to_quarantine_event():
    event_type, metadata = classify_runtime_exception(FloodWait(17))

    assert event_type == AccountHealthEvent.EventType.FLOOD_WAIT
    assert metadata["seconds"] == 17


def test_execute_with_account_guard_reports_success_after_clean_action():
    calls = []

    result = execute_with_account_guard(
        account_id=44,
        action=lambda: "ok",
        reporter=lambda account_id, event_type, metadata: calls.append((account_id, event_type, metadata)),
    )

    assert result == "ok"
    assert calls == [(44, AccountHealthEvent.EventType.SUCCESS, {"source": "worker"})]


def test_execute_with_account_guard_reports_spam_block_before_reraising():
    calls = []

    def action():
        raise PeerFlood(420)

    with pytest.raises(PeerFlood):
        execute_with_account_guard(
            account_id=99,
            action=action,
            reporter=lambda account_id, event_type, metadata: calls.append((account_id, event_type, metadata)),
        )

    assert calls == [(99, AccountHealthEvent.EventType.SPAM_BLOCK, {"error": "PeerFlood"})]


def test_execute_with_account_guard_blocks_paused_account_before_action():
    calls = []

    with pytest.raises(AccountRuntimeBlocked):
        execute_with_account_guard(
            account_id=15,
            action=lambda: calls.append("ran"),
            reporter=lambda account_id, event_type, metadata: calls.append((account_id, event_type, metadata)),
            block_reason_loader=lambda: "Account is quarantined.",
        )

    assert calls == []


def test_execute_async_with_account_guard_reports_success_after_clean_action():
    calls = []

    async def action():
        return "ok"

    result = asyncio.run(
        execute_async_with_account_guard(
            account_id=55,
            action=action,
            reporter=lambda account_id, event_type, metadata: calls.append((account_id, event_type, metadata)),
        )
    )

    assert result == "ok"
    assert calls == [(55, AccountHealthEvent.EventType.SUCCESS, {"source": "worker"})]
