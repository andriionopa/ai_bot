from __future__ import annotations

import math

from celery import shared_task
from django.utils import timezone

from apps.warmup.models import WarmupAction
from apps.warmup.services import execute_warmup_action


@shared_task
def execute_warmup_action_task(action_id: int) -> dict[str, object]:
    if not WarmupAction.objects.filter(pk=action_id).exists():
        return {"action_id": action_id, "status": "deleted"}
    try:
        action = execute_warmup_action(action_id)
    except WarmupAction.DoesNotExist:
        return {"action_id": action_id, "status": "deleted"}
    if action.status == WarmupAction.Status.QUEUED:
        remaining_seconds = max(0, math.ceil((action.scheduled_for - timezone.now()).total_seconds()))
        if remaining_seconds > 0:
            retry_task = execute_warmup_action_task.apply_async(args=[action.id], countdown=remaining_seconds)
            updated = WarmupAction.objects.filter(pk=action.pk).update(celery_task_id=retry_task.id)
            if not updated:
                return {"action_id": action_id, "status": "deleted"}
            return {"action_id": action.id, "status": action.status, "requeued_in": remaining_seconds}
    return {"action_id": action.id, "status": action.status}


@shared_task
def process_due_warmup_actions_task(limit: int = 100) -> int:
    action_ids = list(
        WarmupAction.objects.filter(
            status=WarmupAction.Status.QUEUED,
            scheduled_for__lte=timezone.now(),
            plan__status__in=["running"],
        )
        .order_by("scheduled_for")
        .values_list("id", flat=True)[:limit]
    )
    for action_id in action_ids:
        execute_warmup_action_task.delay(action_id)
    return len(action_ids)
