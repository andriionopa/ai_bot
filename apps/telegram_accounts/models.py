from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class Proxy(models.Model):
    class Protocol(models.TextChoices):
        SOCKS5 = "socks5", "SOCKS5"
        HTTP = "http", "HTTP"

    class Status(models.TextChoices):
        UNKNOWN = "unknown", "Unknown"
        HEALTHY = "healthy", "Healthy"
        DEGRADED = "degraded", "Degraded"
        FAILED = "failed", "Failed"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="proxies")
    name = models.CharField(max_length=255)
    protocol = models.CharField(max_length=16, choices=Protocol.choices, default=Protocol.SOCKS5)
    host = models.GenericIPAddressField()
    port = models.PositiveIntegerField()
    username = models.CharField(max_length=255, blank=True)
    password = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.UNKNOWN)
    is_active = models.BooleanField(default=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_latency_ms = models.PositiveIntegerField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.name} ({self.host}:{self.port})"


class TelegramAccount(models.Model):
    class ConnectSource(models.TextChoices):
        SESSION = "session", "Session"
        CREDENTIALS = "credentials", "Credentials"

    class AuthState(models.TextChoices):
        SESSION_UPLOADED = "session_uploaded", "Session Uploaded"
        PENDING_CODE = "pending_code", "Pending Code"
        PENDING_2FA = "pending_2fa", "Pending 2FA"
        CONNECTED = "connected", "Connected"
        FAILED = "failed", "Failed"
        DETACHED = "detached", "Detached"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        QUARANTINE = "quarantine", "Quarantine"
        BANNED = "banned", "Banned"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="telegram_accounts")
    label = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=32, blank=True)
    session_name = models.CharField(max_length=255, unique=True)
    source = models.CharField(max_length=32, choices=ConnectSource.choices, default=ConnectSource.SESSION)
    auth_state = models.CharField(
        max_length=32,
        choices=AuthState.choices,
        default=AuthState.SESSION_UPLOADED,
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    proxy = models.ForeignKey(Proxy, null=True, blank=True, on_delete=models.SET_NULL, related_name="accounts")
    session_file = models.FileField(upload_to="telegram_sessions/", blank=True)
    is_attached = models.BooleanField(default=True)
    attached_at = models.DateTimeField(default=timezone.now)
    detached_at = models.DateTimeField(null=True, blank=True)
    requires_2fa = models.BooleanField(default=False)
    auth_phone_code_hash = models.CharField(max_length=255, blank=True)
    auth_code_sent_at = models.DateTimeField(null=True, blank=True)
    auth_code_timeout_seconds = models.PositiveIntegerField(null=True, blank=True)
    last_auth_error = models.TextField(blank=True)
    telegram_user_id = models.BigIntegerField(null=True, blank=True)
    telegram_username = models.CharField(max_length=255, blank=True)
    first_name = models.CharField(max_length=255, blank=True)
    last_name = models.CharField(max_length=255, blank=True)
    role = models.CharField(max_length=80, blank=True, default="")
    role_template = models.ForeignKey(
        "telegram_accounts.AccountRoleTemplate",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="accounts",
    )
    birth_date = models.DateField(null=True, blank=True)
    health_score = models.PositiveSmallIntegerField(default=100)
    quarantine_until = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_error_at = models.DateTimeField(null=True, blank=True)
    sleep_min_seconds = models.PositiveIntegerField(default=7)
    sleep_max_seconds = models.PositiveIntegerField(default=42)
    device_model = models.CharField(max_length=255, blank=True, default="")
    system_version = models.CharField(max_length=255, blank=True, default="")
    randomize_device_profile = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.label

    @property
    def is_quarantined(self) -> bool:
        return bool(
            self.status == self.Status.QUARANTINE
            and self.quarantine_until
            and self.quarantine_until > timezone.now()
        )

    @property
    def is_connected(self) -> bool:
        return self.is_attached and self.auth_state == self.AuthState.CONNECTED


class AccountRoleTemplate(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="account_role_templates")
    name = models.CharField(max_length=80)
    prompt = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        unique_together = (("owner", "name"),)
        indexes = [models.Index(fields=("owner", "name"))]

    def __str__(self) -> str:
        return self.name


class AccountHealthEvent(models.Model):
    class EventType(models.TextChoices):
        FLOOD_WAIT = "flood_wait", "Flood Wait"
        SPAM_BLOCK = "spam_block", "Spam Block"
        SUCCESS = "success", "Success"

    account = models.ForeignKey(
        TelegramAccount,
        on_delete=models.CASCADE,
        related_name="health_events",
    )
    event_type = models.CharField(max_length=32, choices=EventType.choices)
    score_delta = models.SmallIntegerField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("account", "event_type", "created_at")),
        ]

    def __str__(self) -> str:
        return f"{self.account_id}:{self.event_type}:{self.created_at.isoformat()}"
