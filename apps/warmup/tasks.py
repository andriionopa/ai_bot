from __future__ import annotations

from celery import shared_task
from django.utils import timezone

from apps.warmup.models import WarmupAction
from apps.warmup.services import execute_warmup_action


@shared_task
def execute_warmup_action_task(action_id: int) -> dict[str, object]:
    if not WarmupAction.objects.filter(pk=action_id).exists():
        return {"action_id": action_id, "status": "deleted"}
    action = execute_warmup_action(action_id)
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
