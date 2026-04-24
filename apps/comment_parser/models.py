from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.telegram_accounts.models import TelegramAccount


class CommentParserConfigMixin(models.Model):
    class SpeedMode(models.TextChoices):
        SAFE = "safe", "Safe"
        BALANCED = "balanced", "Balanced"
        FAST = "fast", "Fast"

    sources = models.JSONField(default=list, blank=True)
    keywords = models.JSONField(default=list, blank=True)
    ai_protection = models.BooleanField(default=True)
    fast_mode = models.BooleanField(default=False)
    speed_mode = models.CharField(max_length=16, choices=SpeedMode.choices, default=SpeedMode.BALANCED)
    post_limit = models.PositiveIntegerField(default=50)
    comment_limit = models.PositiveIntegerField(default=200)
    days_limit = models.PositiveIntegerField(default=30)
    skip_bots = models.BooleanField(default=True)
    skip_deleted = models.BooleanField(default=True)
    skip_scam = models.BooleanField(default=True)
    only_with_username = models.BooleanField(default=False)
    only_with_photo = models.BooleanField(default=False)
    only_premium = models.BooleanField(default=False)
    only_active_users = models.BooleanField(default=False)

    class Meta:
        abstract = True


class CommentParserJob(CommentParserConfigMixin):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        STOPPED = "stopped", "Stopped"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="comment_parser_jobs")
    name = models.CharField(max_length=255)
    accounts = models.ManyToManyField(TelegramAccount, related_name="comment_parser_jobs", blank=True)
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


class ParsedCommenter(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="parsed_commenters")
    job = models.ForeignKey(CommentParserJob, on_delete=models.CASCADE, related_name="results")
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
    comment_count = models.PositiveIntegerField(default=0)
    first_comment_at = models.DateTimeField(null=True, blank=True)
    last_comment_at = models.DateTimeField(null=True, blank=True)
    matched_keywords = models.JSONField(default=list, blank=True)
    sample_comment = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("job", "source_ref", "telegram_user_id", "username")
        indexes = [
            models.Index(fields=("owner", "created_at")),
            models.Index(fields=("job", "comment_count")),
            models.Index(fields=("username",)),
            models.Index(fields=("telegram_user_id",)),
        ]

    def __str__(self) -> str:
        return self.full_name or self.username or str(self.telegram_user_id or self.pk)


class CommentParserLog(models.Model):
    class Level(models.TextChoices):
        INFO = "info", "Info"
        SUCCESS = "success", "Success"
        WARNING = "warning", "Warning"
        ERROR = "error", "Error"
        DEBUG = "debug", "Debug"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="comment_parser_logs")
    job = models.ForeignKey(CommentParserJob, null=True, blank=True, on_delete=models.CASCADE, related_name="logs")
    account = models.ForeignKey(TelegramAccount, null=True, blank=True, on_delete=models.SET_NULL, related_name="comment_parser_logs")
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
