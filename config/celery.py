import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

app = Celery("config")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
app.conf.beat_schedule = {
    "recalculate-account-health-every-15-minutes": {
        "task": "apps.telegram_accounts.tasks.recalculate_all_accounts_health_task",
        "schedule": crontab(minute="*/15"),
    },
    "release-expired-quarantines-every-5-minutes": {
        "task": "apps.telegram_accounts.tasks.release_expired_quarantines_task",
        "schedule": crontab(minute="*/5"),
    },
    "process-due-warmup-actions-every-minute": {
        "task": "apps.warmup.tasks.process_due_warmup_actions_task",
        "schedule": crontab(minute="*"),
    },
}
