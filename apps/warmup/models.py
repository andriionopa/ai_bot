from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.telegram_accounts.models import TelegramAccount


class WarmupPolicy(models.Model):
    class BehaviorProfile(models.TextChoices):
        SAFE = "safe", "Safe"
        BALANCED = "balanced", "Balanced"
        AGGRESSIVE = "aggressive", "Aggressive"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="warmup_policies")
    name = models.CharField(max_length=255)
    behavior_profile = models.CharField(
        max_length=16,
        choices=BehaviorProfile.choices,
        default=BehaviorProfile.SAFE,
    )
    daily_join_min = models.PositiveSmallIntegerField(default=5)
    daily_join_max = models.PositiveSmallIntegerField(default=15)
    delay_min_seconds = models.PositiveIntegerField(default=900)
    delay_max_seconds = models.PositiveIntegerField(default=7200)
    read_min_seconds = models.PositiveIntegerField(default=20)
    read_max_seconds = models.PositiveIntegerField(default=180)
    reaction_probability = models.PositiveSmallIntegerField(default=20)
    max_reactions_per_day = models.PositiveSmallIntegerField(default=5)
    retry_min_seconds = models.PositiveIntegerField(default=1800)
    retry_max_seconds = models.PositiveIntegerField(default=10800)
    active_start_hour = models.PositiveSmallIntegerField(default=8)
    active_end_hour = models.PositiveSmallIntegerField(default=23)
    actions_per_hour = models.PositiveSmallIntegerField(default=15)
    actions_per_day = models.PositiveSmallIntegerField(default=100)
    messages_per_day = models.PositiveSmallIntegerField(default=12)
    session_duration_minutes = models.PositiveIntegerField(default=30)
    random_breaks = models.BooleanField(default=True)
    auto_adapt_limits = models.BooleanField(default=True)
    progressive_ramp = models.BooleanField(default=True)
    allow_folder_one_click = models.BooleanField(default=False)
    allow_public_gradual_join = models.BooleanField(default=True)
    allow_private_join = models.BooleanField(default=True)
    enable_reactions = models.BooleanField(default=True)
    enable_read_channels = models.BooleanField(default=True)
    enable_account_dialogs = models.BooleanField(default=False)
    enable_story_view = models.BooleanField(default=False)
    enable_join_groups = models.BooleanField(default=True)
    enable_trust_boost = models.BooleanField(default=False)
    enable_view_dialogs = models.BooleanField(default=True)
    enable_channel_scroll = models.BooleanField(default=True)
    enable_mark_read = models.BooleanField(default=True)
    enable_message_search = models.BooleanField(default=False)
    enable_forward_messages = models.BooleanField(default=False)
    enable_saved_notes = models.BooleanField(default=False)
    enable_poll_scan = models.BooleanField(default=False)
    enable_video_scan = models.BooleanField(default=False)
    enable_voice_scan = models.BooleanField(default=False)
    enable_gif_search = models.BooleanField(default=False)
    enable_sticker_scan = models.BooleanField(default=False)
    enable_inline_bot_check = models.BooleanField(default=False)
    enable_link_preview = models.BooleanField(default=False)
    enable_typing_simulation = models.BooleanField(default=True)
    enable_profile_view = models.BooleanField(default=False)
    enable_settings_check = models.BooleanField(default=False)
    enable_gradual_profile_check = models.BooleanField(default=False)
    enable_emoji_status_check = models.BooleanField(default=False)
    enable_drafts_check = models.BooleanField(default=False)
    enable_notification_check = models.BooleanField(default=False)
    enable_scheduled_message_check = models.BooleanField(default=False)
    enable_archive_check = models.BooleanField(default=False)
    enable_mute_check = models.BooleanField(default=False)
    search_query = models.CharField(max_length=120, blank=True, default="")
    inline_bot_username = models.CharField(max_length=64, blank=True, default="gif")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=("owner", "is_active")),
            models.Index(fields=("owner", "behavior_profile")),
        ]

    def __str__(self) -> str:
        return self.name


class WarmupTarget(models.Model):
    class TargetType(models.TextChoices):
        CHANNEL = "channel", "Channel"
        FOLDER = "folder", "Folder"

    class Visibility(models.TextChoices):
        PUBLIC = "public", "Public"
        PRIVATE = "private", "Private"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="warmup_targets")
    title = models.CharField(max_length=255)
    target_type = models.CharField(max_length=16, choices=TargetType.choices, default=TargetType.CHANNEL)
    visibility = models.CharField(max_length=16, choices=Visibility.choices, default=Visibility.PUBLIC)
    value = models.CharField(max_length=512)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=("owner", "status")),
            models.Index(fields=("owner", "target_type", "visibility")),
        ]

    def __str__(self) -> str:
        return self.title


class WarmupPlan(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        RUNNING = "running", "Running"
        PAUSED = "paused", "Paused"
        COMPLETED = "completed", "Completed"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="warmup_plans")
    name = models.CharField(max_length=255)
    policy = models.ForeignKey(WarmupPolicy, on_delete=models.PROTECT, related_name="plans")
    accounts = models.ManyToManyField(TelegramAccount, related_name="warmup_plans", blank=True)
    targets = models.ManyToManyField(WarmupTarget, related_name="warmup_plans", blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=("owner", "status", "created_at")),
            models.Index(fields=("policy", "status")),
        ]

    def __str__(self) -> str:
        return self.name


class WarmupAction(models.Model):
    class ActionType(models.TextChoices):
        JOIN_CHANNEL = "join_channel", "Join Channel"
        JOIN_FOLDER = "join_folder", "Join Folder"
        VIEW_DIALOGS = "view_dialogs", "View Dialogs"
        CHANNEL_SCROLL = "channel_scroll", "Channel Scroll"
        READ = "read", "Read"
        ACCOUNT_DIALOG = "account_dialog", "Account Dialog"
        STORY_VIEW = "story_view", "Story View"
        TRUST_BOOST = "trust_boost", "Trust Boost"
        MARK_READ = "mark_read", "Mark Read"
        MESSAGE_SEARCH = "message_search", "Message Search"
        REACTION = "reaction", "Reaction"
        FORWARD_MESSAGE = "forward_message", "Forward Message"
        SAVED_NOTE = "saved_note", "Saved Note"
        POLL_SCAN = "poll_scan", "Poll Scan"
        VIDEO_SCAN = "video_scan", "Video Scan"
        VOICE_SCAN = "voice_scan", "Voice Scan"
        GIF_SEARCH = "gif_search", "GIF Search"
        STICKER_SCAN = "sticker_scan", "Sticker Scan"
        INLINE_BOT_CHECK = "inline_bot_check", "Inline Bot Check"
        LINK_PREVIEW = "link_preview", "Link Preview"
        TYPING_SIMULATION = "typing_simulation", "Typing Simulation"
        PROFILE_VIEW = "profile_view", "Profile View"
        SETTINGS_CHECK = "settings_check", "Settings Check"
        GRADUAL_PROFILE_CHECK = "gradual_profile_check", "Gradual Profile Check"
        EMOJI_STATUS_CHECK = "emoji_status_check", "Emoji Status Check"
        DRAFTS_CHECK = "drafts_check", "Drafts Check"
        NOTIFICATION_CHECK = "notification_check", "Notification Check"
        SCHEDULED_MESSAGE_CHECK = "scheduled_message_check", "Scheduled Message Check"
        ARCHIVE_CHECK = "archive_check", "Archive Check"
        MUTE_CHECK = "mute_check", "Mute Check"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="warmup_actions")
    plan = models.ForeignKey(WarmupPlan, on_delete=models.CASCADE, related_name="actions")
    account = models.ForeignKey(TelegramAccount, on_delete=models.CASCADE, related_name="warmup_actions")
    target = models.ForeignKey(WarmupTarget, on_delete=models.CASCADE, related_name="actions")
    action_type = models.CharField(max_length=32, choices=ActionType.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    scheduled_for = models.DateTimeField(default=timezone.now)
    delay_seconds = models.PositiveIntegerField(default=0)
    celery_task_id = models.CharField(max_length=255, blank=True, db_index=True)
    attempt = models.PositiveSmallIntegerField(default=0)
    error = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=("owner", "status", "scheduled_for")),
            models.Index(fields=("plan", "status", "scheduled_for")),
            models.Index(fields=("account", "status", "scheduled_for")),
        ]

    def __str__(self) -> str:
        return f"{self.account_id}:{self.action_type}:{self.status}"


class WarmupLog(models.Model):
    class Level(models.TextChoices):
        INFO = "info", "Info"
        SUCCESS = "success", "Success"
        WARNING = "warning", "Warning"
        ERROR = "error", "Error"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="warmup_logs")
    plan = models.ForeignKey(WarmupPlan, null=True, blank=True, on_delete=models.CASCADE, related_name="logs")
    action = models.ForeignKey(WarmupAction, null=True, blank=True, on_delete=models.SET_NULL, related_name="logs")
    account = models.ForeignKey(TelegramAccount, null=True, blank=True, on_delete=models.SET_NULL, related_name="warmup_logs")
    level = models.CharField(max_length=16, choices=Level.choices, default=Level.INFO)
    message = models.CharField(max_length=500)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("owner", "created_at")),
            models.Index(fields=("account", "created_at")),
            models.Index(fields=("plan", "created_at")),
        ]

    def __str__(self) -> str:
        return f"{self.created_at:%H:%M:%S} {self.level} {self.message}"
