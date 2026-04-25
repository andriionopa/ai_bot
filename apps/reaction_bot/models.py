from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.telegram_accounts.models import TelegramAccount

HARDCODED_EMOJIS = ["👍", "❤", "🔥", "😁", "🤔", "👏", "🙏", "🎉"]


class AccountChannelBinding(models.Model):
    """Binds a Telegram account to a channel identity for Premium reaction-from-channel."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="account_channel_bindings")
    account = models.ForeignKey(TelegramAccount, on_delete=models.CASCADE, related_name="channel_bindings")
    channel_username = models.CharField(max_length=255)
    title = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("owner", "account", "channel_username")
        indexes = [
            models.Index(fields=("owner", "account")),
        ]

    def __str__(self) -> str:
        return f"{self.account.label} → @{self.channel_username}"


class ReactionJob(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        STOPPED = "stopped", "Stopped"

    class SpeedMode(models.TextChoices):
        SAFE = "safe", "Safe"
        BALANCED = "balanced", "Balanced"
        FAST = "fast", "Fast"

    class EmojiMode(models.TextChoices):
        RANDOM = "random", "Random"
        SEQUENTIAL = "sequential", "Sequential"

    class WorkMode(models.TextChoices):
        MONITORING = "monitoring", "Monitoring"
        EXISTING = "existing", "Existing"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reaction_jobs")
    name = models.CharField(max_length=255)
    accounts = models.ManyToManyField(TelegramAccount, related_name="reaction_jobs", blank=True)

    # Sources
    sources = models.JSONField(default=list, blank=True)

    # Reaction config
    emojis = models.JSONField(default=list, blank=True)
    emoji_mode = models.CharField(max_length=16, choices=EmojiMode.choices, default=EmojiMode.RANDOM)
    reaction_probability = models.FloatField(default=1.0)

    # Work mode
    work_mode = models.CharField(max_length=16, choices=WorkMode.choices, default=WorkMode.EXISTING)
    post_limit = models.PositiveIntegerField(default=20)
    max_reactions = models.PositiveIntegerField(default=0)
    duration_minutes = models.PositiveIntegerField(default=60)

    # Delays (seconds)
    reaction_delay_min = models.FloatField(default=3.0)
    reaction_delay_max = models.FloatField(default=10.0)
    entry_delay_min = models.FloatField(default=0.0)
    entry_delay_max = models.FloatField(default=5.0)

    # AI protection
    ai_protection = models.BooleanField(default=True)
    speed_mode = models.CharField(max_length=16, choices=SpeedMode.choices, default=SpeedMode.BALANCED)

    # Premium: react from channel identity
    use_channel_identity = models.BooleanField(default=False)
    channel_bindings = models.ManyToManyField(AccountChannelBinding, related_name="reaction_jobs", blank=True)

    # Account rotation
    account_rotation = models.BooleanField(default=True)

    # React in random subscribed channels/groups
    use_subscriptions = models.BooleanField(default=False)
    subscriptions_limit = models.PositiveIntegerField(default=50)

    # AI features
    ai_smart_emoji = models.BooleanField(default=False)

    # React to commenters in discussion groups
    react_to_comments = models.BooleanField(default=False)
    comment_reaction_probability = models.FloatField(default=0.3)

    # Progress / state
    reactions_sent = models.PositiveIntegerField(default=0)
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


class ReactionLog(models.Model):
    class Level(models.TextChoices):
        INFO = "info", "Info"
        SUCCESS = "success", "Success"
        WARNING = "warning", "Warning"
        ERROR = "error", "Error"
        DEBUG = "debug", "Debug"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reaction_logs")
    job = models.ForeignKey(ReactionJob, null=True, blank=True, on_delete=models.CASCADE, related_name="logs")
    account = models.ForeignKey(TelegramAccount, null=True, blank=True, on_delete=models.SET_NULL, related_name="reaction_logs")
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
