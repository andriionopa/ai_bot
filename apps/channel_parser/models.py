from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.telegram_accounts.models import TelegramAccount


class ChannelParserConfigMixin(models.Model):
    class ParseType(models.TextChoices):
        CHANNELS = "channels", "Channels"
        GROUPS = "groups", "Groups"

    class SpeedMode(models.TextChoices):
        SAFE = "safe", "Safe"
        BALANCED = "balanced", "Balanced"
        FAST = "fast", "Fast"

    class ActivityFilter(models.TextChoices):
        ANY = "any", "Any"
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"

    class CommentsFilter(models.TextChoices):
        ANY = "any", "Any"
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"

    class SearchScope(models.TextChoices):
        GLOBAL = "global", "Global"
        SUBSCRIPTIONS = "subscriptions", "Subscriptions"
        BOTH = "both", "Both"

    keywords = models.JSONField(default=list, blank=True)
    suffixes = models.JSONField(default=list, blank=True)
    parse_type = models.CharField(max_length=16, choices=ParseType.choices, default=ParseType.CHANNELS)
    search_scope = models.CharField(max_length=16, choices=SearchScope.choices, default=SearchScope.BOTH)
    ai_protection = models.BooleanField(default=True)
    fast_mode = models.BooleanField(default=False)
    speed_mode = models.CharField(max_length=16, choices=SpeedMode.choices, default=SpeedMode.BALANCED)
    activity_filter = models.CharField(max_length=16, choices=ActivityFilter.choices, default=ActivityFilter.ANY)
    comments_filter = models.CharField(max_length=16, choices=CommentsFilter.choices, default=CommentsFilter.ANY)
    result_limit = models.PositiveIntegerField(default=50)
    subscriber_min = models.PositiveIntegerField(default=500)
    subscriber_max = models.PositiveIntegerField(default=1_000_000)
    rating_min = models.PositiveSmallIntegerField(default=5)
    language_detection = models.BooleanField(default=True)
    languages = models.JSONField(default=list, blank=True)
    request_delay_seconds = models.FloatField(default=2.0)
    channel_delay_seconds = models.FloatField(default=1.0)

    class Meta:
        abstract = True


class ChannelParserJob(ChannelParserConfigMixin):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        STOPPED = "stopped", "Stopped"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="channel_parser_jobs")
    name = models.CharField(max_length=255)
    accounts = models.ManyToManyField(TelegramAccount, related_name="channel_parser_jobs", blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    celery_task_id = models.CharField(max_length=255, blank=True, db_index=True)
    error = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=("owner", "status", "created_at")),
        ]

    def __str__(self) -> str:
        return self.name


class ChannelParserTemplate(ChannelParserConfigMixin):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="channel_parser_templates")
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=("owner", "name")),
            models.Index(fields=("owner", "created_at")),
        ]

    def __str__(self) -> str:
        return self.name


class ChannelCollectionTemplate(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="channel_collection_templates")
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=("owner", "name")),
            models.Index(fields=("owner", "created_at")),
        ]
        constraints = [
            models.UniqueConstraint(fields=("owner", "name"), name="channel_collection_template_owner_name_uniq"),
        ]

    def __str__(self) -> str:
        return self.name


class ChannelCollectionItem(models.Model):
    class EntityType(models.TextChoices):
        CHANNEL = "channel", "Channel"
        GROUP = "group", "Group"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="channel_collection_items")
    template = models.ForeignKey(ChannelCollectionTemplate, on_delete=models.CASCADE, related_name="items")
    source_job = models.ForeignKey("ChannelParserJob", null=True, blank=True, on_delete=models.SET_NULL, related_name="template_items")
    title = models.CharField(max_length=255)
    username = models.CharField(max_length=255, blank=True)
    url = models.URLField(max_length=512, blank=True)
    telegram_id = models.BigIntegerField(null=True, blank=True)
    entity_type = models.CharField(max_length=16, choices=EntityType.choices, default=EntityType.CHANNEL)
    subscribers = models.PositiveIntegerField(default=0)
    rating = models.PositiveSmallIntegerField(default=0)
    language = models.CharField(max_length=16, blank=True)
    activity_level = models.CharField(max_length=16, blank=True)
    comments_open = models.BooleanField(null=True, blank=True)
    matched_query = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=("owner", "created_at")),
            models.Index(fields=("template", "created_at")),
            models.Index(fields=("template", "username")),
            models.Index(fields=("template", "telegram_id")),
        ]

    def __str__(self) -> str:
        return f"{self.template_id}:{self.title}"


class ParsedChannel(models.Model):
    class EntityType(models.TextChoices):
        CHANNEL = "channel", "Channel"
        GROUP = "group", "Group"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="parsed_channels")
    job = models.ForeignKey(ChannelParserJob, on_delete=models.CASCADE, related_name="results")
    title = models.CharField(max_length=255)
    username = models.CharField(max_length=255, blank=True)
    url = models.URLField(max_length=512, blank=True)
    telegram_id = models.BigIntegerField(null=True, blank=True)
    entity_type = models.CharField(max_length=16, choices=EntityType.choices, default=EntityType.CHANNEL)
    subscribers = models.PositiveIntegerField(default=0)
    rating = models.PositiveSmallIntegerField(default=0)
    language = models.CharField(max_length=16, blank=True)
    activity_level = models.CharField(max_length=16, blank=True)
    comments_open = models.BooleanField(null=True, blank=True)
    last_post_at = models.DateTimeField(null=True, blank=True)
    matched_query = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("owner", "username", "telegram_id")
        indexes = [
            models.Index(fields=("owner", "created_at")),
            models.Index(fields=("job", "rating")),
            models.Index(fields=("username",)),
        ]

    def __str__(self) -> str:
        return self.title


class ChannelParserLog(models.Model):
    class Level(models.TextChoices):
        INFO = "info", "Info"
        SUCCESS = "success", "Success"
        WARNING = "warning", "Warning"
        ERROR = "error", "Error"
        DEBUG = "debug", "Debug"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="channel_parser_logs")
    job = models.ForeignKey(ChannelParserJob, null=True, blank=True, on_delete=models.CASCADE, related_name="logs")
    account = models.ForeignKey(TelegramAccount, null=True, blank=True, on_delete=models.SET_NULL, related_name="channel_parser_logs")
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
