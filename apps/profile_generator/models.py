from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class ProfileDraft(models.Model):
    class Gender(models.TextChoices):
        FEMALE = "female", "Female"
        MALE = "male", "Male"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        GENERATED = "generated", "Generated"
        APPLIED = "applied", "Applied"
        FAILED = "failed", "Failed"

    class ImageSource(models.TextChoices):
        NONE = "none", "None"
        AI = "ai", "AI"
        UPLOAD = "upload", "Upload"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile_drafts")
    account = models.ForeignKey(
        "telegram_accounts.TelegramAccount",
        on_delete=models.CASCADE,
        related_name="profile_drafts",
    )
    gender = models.CharField(max_length=16, choices=Gender.choices)
    age = models.PositiveSmallIntegerField(null=True, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    country = models.CharField(max_length=120)
    profession = models.CharField(max_length=160)
    telegram_channel = models.CharField(max_length=160, blank=True)
    bio = models.CharField(max_length=70, blank=True)
    photo = models.FileField(upload_to="profile_generator/photos/", blank=True)
    photo_prompt = models.TextField(blank=True)
    image_source = models.CharField(max_length=16, choices=ImageSource.choices, default=ImageSource.NONE)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    provider_payload = models.JSONField(default=dict, blank=True)
    last_error = models.TextField(blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("owner", "status", "created_at")),
            models.Index(fields=("account", "status")),
        ]

    def mark_failed(self, error: str) -> None:
        self.status = self.Status.FAILED
        self.last_error = error
        self.save(update_fields=["status", "last_error", "updated_at"])

    def mark_applied(self) -> None:
        self.status = self.Status.APPLIED
        self.applied_at = timezone.now()
        self.last_error = ""
        self.save(update_fields=["status", "applied_at", "last_error", "updated_at"])

    def __str__(self) -> str:
        age = self.age or "unknown-age"
        return f"{self.account_id}: {self.gender} {age} {self.profession}"
