from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.telegram_accounts.models import TelegramAccount


class MessageParserConfigMixin(models.Model):
    class SpeedMode(models.TextChoices):
        SAFE = "safe", "Safe"
        BALANCED = "balanced", "Balanced"
        FAST = "fast", "Fast"

    keywords = models.JSONField(default=list, blank=True)
    sources = models.JSONField(default=list, blank=True)
    ai_protection = models.BooleanField(default=True)
    fast_mode = models.BooleanField(default=False)
    speed_mode = models.CharField(max_length=16, choices=SpeedMode.choices, default=SpeedMode.BALANCED)
    message_limit = models.PositiveIntegerField(default=1000)
    days_limit = models.PositiveIntegerField(default=30)
    skip_bots = models.BooleanField(default=True)
    skip_deleted = models.BooleanField(default=True)
    skip_scam = models.BooleanField(default=True)
    only_with_username = models.BooleanField(default=False)
    only_with_photo = models.BooleanField(default=False)
    only_premium = models.BooleanField(default=False)
    only_active_users = models.BooleanField(default=False)
    include_forwards = models.BooleanField(default=False)
    include_replies = models.BooleanField(default=True)

    class Meta:
        abstract = True


class MessageParserJob(MessageParserConfigMixin):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        STOPPED = "stopped", "Stopped"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="message_parser_jobs")
    name = models.CharField(max_length=255)
    accounts = models.ManyToManyField(TelegramAccount, related_name="message_parser_jobs", blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    celery_task_id = models.CharField(max_length=255, blank=True, db_index=True)
    error = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=("owner", "status", "created_at"))]

    def __str__(self) -> str:
        return self.name


class ParsedUser(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="parsed_users")
    job = models.ForeignKey(MessageParserJob, on_delete=models.CASCADE, related_name="results")
    source_ref = models.CharField(max_length=255, blank=True)
    source_title = models.CharField(max_length=255, blank=True)
    source_username = models.CharField(max_length=255, blank=True)
    source_url = models.URLField(max_length=512, blank=True)
    telegram_user_id = models.BigIntegerField(null=True, blank=True)
    username = models.CharField(max_length=255, blank=True)
    full_name = models.CharField(max_length=255, blank=True)
    profile_url = models.URLField(max_length=512, blank=True)
    is_bot = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    is_scam = models.BooleanField(default=False)
    is_premium = models.BooleanField(default=False)
    has_photo = models.BooleanField(default=False)
    message_count = models.PositiveIntegerField(default=0)
    first_message_at = models.DateTimeField(null=True, blank=True)
    last_message_at = models.DateTimeField(null=True, blank=True)
    matched_keywords = models.JSONField(default=list, blank=True)
    sample_message = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("job", "source_ref", "telegram_user_id", "username")
        indexes = [
            models.Index(fields=("owner", "created_at")),
            models.Index(fields=("job", "message_count")),
            models.Index(fields=("username",)),
            models.Index(fields=("telegram_user_id",)),
        ]

    def __str__(self) -> str:
        return self.full_name or self.username or str(self.telegram_user_id or self.pk)


class MessageParserLog(models.Model):
    class Level(models.TextChoices):
        INFO = "info", "Info"
        SUCCESS = "success", "Success"
        WARNING = "warning", "Warning"
        ERROR = "error", "Error"
        DEBUG = "debug", "Debug"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="message_parser_logs")
    job = models.ForeignKey(MessageParserJob, null=True, blank=True, on_delete=models.CASCADE, related_name="logs")
    account = models.ForeignKey(TelegramAccount, null=True, blank=True, on_delete=models.SET_NULL, related_name="message_parser_logs")
    level = models.CharField(max_length=16, choices=Level.choices, default=Level.INFO)
    message = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at",)
        indexes = [
            models.Index(fields=("owner", "created_at")),
            models.Index(fields=("job", "created_at")),
            models.Index(fields=("level",)),
        ]

    def __str__(self) -> str:
        return self.message[:80]
