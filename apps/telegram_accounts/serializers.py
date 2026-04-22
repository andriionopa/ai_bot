from __future__ import annotations

import re

from django.conf import settings
from rest_framework import serializers

from apps.input_validation import validate_json_object_size, validate_pyrogram_session_file
from apps.telegram_accounts.models import AccountHealthEvent, Proxy, TelegramAccount


PHONE_RE = re.compile(r"^\+?[1-9]\d{7,14}$")


def normalize_label(value: str) -> str:
    value = " ".join((value or "").strip().split())
    if not value:
        raise serializers.ValidationError("Label is required.")
    return value


def normalize_phone_number(value: str) -> str:
    value = (value or "").strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if value and not PHONE_RE.fullmatch(value):
        raise serializers.ValidationError("Phone number must be in international format, for example +380671112233.")
    return value


class TelegramAccountSerializer(serializers.ModelSerializer):
    proxy = serializers.PrimaryKeyRelatedField(queryset=Proxy.objects.none(), required=False, allow_null=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            self.fields["proxy"].queryset = Proxy.objects.filter(owner=request.user, is_active=True)

    class Meta:
        model = TelegramAccount
        fields = (
            "id",
            "label",
            "phone_number",
            "session_name",
            "source",
            "auth_state",
            "status",
            "proxy",
            "session_file",
            "is_attached",
            "attached_at",
            "detached_at",
            "requires_2fa",
            "auth_code_sent_at",
            "auth_code_timeout_seconds",
            "last_auth_error",
            "telegram_user_id",
            "telegram_username",
            "first_name",
            "last_name",
            "health_score",
            "quarantine_until",
            "sleep_min_seconds",
            "sleep_max_seconds",
            "device_model",
            "system_version",
            "randomize_device_profile",
            "created_at",
        )
        read_only_fields = (
            "session_name",
            "source",
            "auth_state",
            "status",
            "session_file",
            "is_attached",
            "attached_at",
            "detached_at",
            "requires_2fa",
            "auth_code_sent_at",
            "auth_code_timeout_seconds",
            "last_auth_error",
            "telegram_user_id",
            "telegram_username",
            "first_name",
            "last_name",
            "health_score",
            "quarantine_until",
            "created_at",
        )

    def validate_label(self, value):
        return normalize_label(value)

    def validate_phone_number(self, value):
        return normalize_phone_number(value)

    def validate_device_model(self, value):
        return " ".join((value or "").strip().split())

    def validate_system_version(self, value):
        return " ".join((value or "").strip().split())

    def validate(self, attrs):
        sleep_min = attrs.get("sleep_min_seconds", getattr(self.instance, "sleep_min_seconds", None))
        sleep_max = attrs.get("sleep_max_seconds", getattr(self.instance, "sleep_max_seconds", None))
        if sleep_min is not None and sleep_max is not None:
            if sleep_min < 1 or sleep_max < 1:
                raise serializers.ValidationError({"sleep_min_seconds": "Sleep values must be positive."})
            if sleep_min > sleep_max:
                raise serializers.ValidationError({"sleep_max_seconds": "sleep_max_seconds must be >= sleep_min_seconds."})
            if sleep_max > 24 * 60 * 60:
                raise serializers.ValidationError({"sleep_max_seconds": "Sleep delay cannot exceed 24 hours."})
        return attrs


class ProxySerializer(serializers.ModelSerializer):
    accounts = TelegramAccountSerializer(many=True, read_only=True)

    class Meta:
        model = Proxy
        fields = (
            "id",
            "name",
            "protocol",
            "host",
            "port",
            "username",
            "password",
            "status",
            "is_active",
            "last_checked_at",
            "last_latency_ms",
            "last_error",
            "accounts",
        )
        read_only_fields = ("status", "last_checked_at", "last_latency_ms", "last_error")

    def validate_name(self, value):
        return normalize_label(value)

    def validate_port(self, value):
        if value < 1 or value > 65535:
            raise serializers.ValidationError("Port must be between 1 and 65535.")
        return value

    def validate_username(self, value):
        return (value or "").strip()

    def validate_password(self, value):
        return (value or "").strip()


class AccountHealthEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountHealthEvent
        fields = ("id", "event_type", "score_delta", "metadata", "created_at")


class AccountRuntimeEventCreateSerializer(serializers.Serializer):
    event_type = serializers.ChoiceField(choices=AccountHealthEvent.EventType.choices)
    metadata = serializers.JSONField(required=False)

    def validate_metadata(self, value):
        validate_json_object_size(value, max_bytes=settings.RUNTIME_METADATA_MAX_BYTES, field_name="metadata")
        return value


class TelegramAccountAttachSerializer(serializers.Serializer):
    attach_mode = serializers.ChoiceField(
        choices=(
            (TelegramAccount.ConnectSource.SESSION, "Session"),
            (TelegramAccount.ConnectSource.CREDENTIALS, "Credentials"),
        )
    )
    label = serializers.CharField(max_length=255)
    phone_number = serializers.CharField(max_length=32, required=False, allow_blank=True)
    proxy = serializers.PrimaryKeyRelatedField(queryset=Proxy.objects.none(), required=False, allow_null=True)
    session_file = serializers.FileField(required=False)
    requires_2fa = serializers.BooleanField(required=False, default=False)
    device_model = serializers.CharField(max_length=255, required=False, allow_blank=True)
    system_version = serializers.CharField(max_length=255, required=False, allow_blank=True)
    randomize_device_profile = serializers.BooleanField(required=False, default=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            self.fields["proxy"].queryset = Proxy.objects.filter(owner=request.user, is_active=True)

    def validate(self, attrs):
        attach_mode = attrs["attach_mode"]
        if attach_mode == TelegramAccount.ConnectSource.SESSION and not attrs.get("session_file"):
            raise serializers.ValidationError({"session_file": "Session file is required."})
        if attach_mode == TelegramAccount.ConnectSource.CREDENTIALS and not attrs.get("phone_number"):
            raise serializers.ValidationError({"phone_number": "Phone number is required."})
        return attrs

    def validate_label(self, value):
        return normalize_label(value)

    def validate_phone_number(self, value):
        return normalize_phone_number(value)

    def validate_session_file(self, value):
        validate_pyrogram_session_file(value)
        return value

    def validate_device_model(self, value):
        return " ".join((value or "").strip().split())

    def validate_system_version(self, value):
        return " ".join((value or "").strip().split())


class TelegramAccountCompleteAuthSerializer(serializers.Serializer):
    verification_code = serializers.CharField(max_length=32, required=False, allow_blank=True)
    password_2fa = serializers.CharField(max_length=255, required=False, allow_blank=True, trim_whitespace=False)

    def validate_verification_code(self, value):
        value = (value or "").strip().replace(" ", "")
        if value and not value.isdigit():
            raise serializers.ValidationError("Verification code must contain digits only.")
        if value and len(value) > 12:
            raise serializers.ValidationError("Verification code is too long.")
        return value


class TelegramAccountProxyAssignSerializer(serializers.Serializer):
    proxy = serializers.PrimaryKeyRelatedField(queryset=Proxy.objects.none(), required=False, allow_null=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            self.fields["proxy"].queryset = Proxy.objects.filter(owner=request.user, is_active=True)


class TelegramAccountBulkDetachSerializer(serializers.Serializer):
    account_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=False, max_length=500)

    def validate_account_ids(self, value):
        return list(dict.fromkeys(value))


class FarmOverviewSerializer(serializers.Serializer):
    account_count = serializers.IntegerField()
    attached_count = serializers.IntegerField()
    connected_count = serializers.IntegerField()
    quarantined_count = serializers.IntegerField()
    pending_auth_count = serializers.IntegerField()
    proxy_count = serializers.IntegerField()
    accounts = TelegramAccountSerializer(many=True)
    proxies = ProxySerializer(many=True)


class TelegramAccountHealthSerializer(serializers.ModelSerializer):
    recent_events = serializers.SerializerMethodField()
    is_quarantined = serializers.BooleanField(read_only=True)
    recommended_pause_range = serializers.SerializerMethodField()

    class Meta:
        model = TelegramAccount
        fields = (
            "id",
            "label",
            "status",
            "health_score",
            "quarantine_until",
            "is_quarantined",
            "last_success_at",
            "last_error_at",
            "sleep_min_seconds",
            "sleep_max_seconds",
            "device_model",
            "system_version",
            "randomize_device_profile",
            "recommended_pause_range",
            "recent_events",
        )

    def get_recent_events(self, obj):
        events = obj.health_events.all()[:10]
        return AccountHealthEventSerializer(events, many=True).data

    def get_recommended_pause_range(self, obj):
        return {"min_seconds": obj.sleep_min_seconds, "max_seconds": obj.sleep_max_seconds}
