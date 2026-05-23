from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.telegram_accounts.models import TelegramAccount

SYSTEM_PROMPTS = [
    ("positive", "Позитивний коментар", "Напиши короткий позитивний коментар до поста в Telegram-каналі. Коментар має бути природним, доброзичливим і відповідати темі поста. 1–2 речення."),
    ("intimate", "Інтимний", "Напиши особистий, теплий коментар до поста в Telegram-каналі. Звертайся до теми поста як до близького, зрозумілого явища. 1–2 речення."),
    ("emotional", "Емоційний відклик", "Напиши емоційний коментар до поста в Telegram-каналі, що передає живу реакцію читача. 1–2 речення."),
    ("question", "Вопрос автору", "Напиши коментар-запитання до автора поста в Telegram-каналі. Запитання має бути доречним і стимулювати дискусію. 1 речення."),
    ("review", "Краткий відгук", "Напиши стислий відгук-коментар до поста в Telegram-каналі. Підсумуй своє враження одним-двома реченнями."),
    ("analytical", "Аналітичний підхід", "Напиши аналітичний коментар до поста в Telegram-каналі. Виділи ключову думку або зроби спостереження. 1–2 речення."),
]


class NeuroCommentPrompt(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="neuro_comment_prompts"
    )
    name = models.CharField(max_length=120)
    text = models.TextField()
    is_system = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("is_system", "name")
        unique_together = (("owner", "name"),)

    def __str__(self) -> str:
        return self.name


class NeuroCommentJob(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        STOPPED = "stopped", "Stopped"

    class CommentMode(models.TextChoices):
        ALL = "all", "Всі пости"
        KEYWORD = "keyword", "За ключовими словами"
        RANDOM = "random", "Випадкові"

    class WorkMode(models.TextChoices):
        MONITORING = "monitoring", "Моніторинг нових постів"
        COUNT = "count", "За кількістю коментарів"

    class LanguageMode(models.TextChoices):
        AUTO = "auto", "Авто (визначати з поста)"
        MANUAL = "manual", "Вручну"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="neuro_comment_jobs"
    )
    name = models.CharField(max_length=255)
    accounts = models.ManyToManyField(TelegramAccount, related_name="neuro_comment_jobs", blank=True)

    # Target channels
    sources = models.JSONField(default=list, blank=True)

    # AI prompt settings
    use_ai_prompt = models.BooleanField(default=True)
    selected_prompts = models.ManyToManyField(
        NeuroCommentPrompt, related_name="jobs", blank=True
    )

    # Comment mode
    comment_mode = models.CharField(max_length=16, choices=CommentMode.choices, default=CommentMode.ALL)
    keywords = models.JSONField(default=list, blank=True)
    random_probability = models.FloatField(default=0.5)

    # Work mode
    work_mode = models.CharField(max_length=16, choices=WorkMode.choices, default=WorkMode.MONITORING)
    max_comments = models.PositiveIntegerField(default=0)
    duration_minutes = models.PositiveIntegerField(default=60)

    # Language
    language_mode = models.CharField(max_length=16, choices=LanguageMode.choices, default=LanguageMode.AUTO)
    language = models.CharField(max_length=8, default="ru", blank=True)

    # Write as channel (Premium)
    write_as_channel = models.BooleanField(default=False)
    write_as_channel_username = models.CharField(max_length=255, blank=True)

    # Auto-responder in DMs
    auto_reply_enabled = models.BooleanField(default=False)
    auto_reply_message = models.TextField(blank=True)

    # First message strategy: send emoji → edit to real comment
    first_message_strategy = models.BooleanField(default=False)
    first_message_text = models.CharField(max_length=64, default="👍", blank=True)
    first_message_edit_delay = models.PositiveIntegerField(default=45)

    # Account rotation
    account_rotation = models.BooleanField(default=True)
    rotation_every_n = models.PositiveIntegerField(default=5)

    # Delays (seconds)
    comment_delay_min = models.FloatField(default=53.0)
    comment_delay_max = models.FloatField(default=99.0)
    entry_delay_min = models.FloatField(default=84.0)
    entry_delay_max = models.FloatField(default=156.0)

    # AI protection
    ai_protection = models.BooleanField(default=True)

    # Progress / state
    comments_sent = models.PositiveIntegerField(default=0)
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


class NeuroCommentLog(models.Model):
    class Level(models.TextChoices):
        INFO = "info", "Info"
        SUCCESS = "success", "Success"
        WARNING = "warning", "Warning"
        ERROR = "error", "Error"
        DEBUG = "debug", "Debug"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="neuro_comment_logs"
    )
    job = models.ForeignKey(
        NeuroCommentJob, null=True, blank=True, on_delete=models.CASCADE, related_name="logs"
    )
    account = models.ForeignKey(
        TelegramAccount, null=True, blank=True, on_delete=models.SET_NULL, related_name="neuro_comment_logs"
    )
    channel = models.CharField(max_length=255, blank=True)
    post_text = models.TextField(blank=True)
    comment_text = models.TextField(blank=True)
    prompt_name = models.CharField(max_length=120, blank=True)
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


class NeuroCommentBlacklist(models.Model):
    class Reason(models.TextChoices):
        FLOOD_WAIT = "flood_wait", "FloodWait"
        BANNED = "banned", "Banned"
        DELETED = "deleted", "Comment deleted"
        MANUAL = "manual", "Manual"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="neuro_comment_blacklist"
    )
    job = models.ForeignKey(
        NeuroCommentJob, null=True, blank=True, on_delete=models.SET_NULL, related_name="blacklist"
    )
    account = models.ForeignKey(
        TelegramAccount, null=True, blank=True, on_delete=models.SET_NULL, related_name="neuro_comment_blacklist"
    )
    channel_username = models.CharField(max_length=255)
    reason = models.CharField(max_length=32, choices=Reason.choices, default=Reason.MANUAL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("owner", "channel_username")),
        ]

    def __str__(self) -> str:
        return f"{self.channel_username} ({self.reason})"
