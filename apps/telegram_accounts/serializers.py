from __future__ import annotations

import re

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers

from apps.input_validation import validate_json_object_size, validate_pyrogram_session_file
from apps.telegram_accounts.models import AccountHealthEvent, AccountRoleTemplate, Proxy, TelegramAccount
from apps.telegram_accounts.services import account_liveness_score, account_risk_level


PHONE_RE = re.compile(r"^\+?[1-9]\d{7,14}$")

WARMUP_ACTION_STATUS_LABELS = {
    "join_channel": "Вступ у канал",
    "join_folder": "Вступ через папку",
    "view_dialogs": "Перегляд діалогів",
    "channel_scroll": "Прокрутка каналу",
    "read": "Читання постів",
    "account_dialog": "Діалог між акаунтами",
    "story_view": "Перегляд сторіс",
    "trust_boost": "Підвищення довіри",
    "mark_read": "Позначення прочитаним",
    "message_search": "Пошук повідомлень",
    "reaction": "Реакція на пост",
    "forward_message": "Пересилка",
    "saved_note": "Нотатка",
    "poll_scan": "Пошук опитувань",
    "video_scan": "Перегляд відео",
    "voice_scan": "Прослуховування voice",
    "gif_search": "Пошук GIF",
    "sticker_scan": "Перегляд стікерів",
    "inline_bot_check": "Inline-бот",
    "link_preview": "Preview посилань",
    "typing_simulation": "Симуляція набору",
    "profile_view": "Перегляд профілю",
    "settings_check": "Налаштування",
    "gradual_profile_check": "Перевірка профілю",
    "emoji_status_check": "Emoji-status",
    "drafts_check": "Чернетки",
    "notification_check": "Сповіщення",
    "scheduled_message_check": "Відкладене повідомлення",
    "archive_check": "Архів",
    "mute_check": "Mute",
}


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
    avatar_url = serializers.SerializerMethodField()
    role_template = serializers.PrimaryKeyRelatedField(queryset=AccountRoleTemplate.objects.none(), required=False, allow_null=True)
    role_template_detail = serializers.SerializerMethodField()
    is_quarantined = serializers.BooleanField(read_only=True)
    liveness_score = serializers.SerializerMethodField()
    risk_level = serializers.SerializerMethodField()
    operational_role = serializers.SerializerMethodField()
    operational_role_label = serializers.SerializerMethodField()
    warmup_age_days = serializers.SerializerMethodField()
    current_warmup_action_type = serializers.SerializerMethodField()
    current_warmup_action_status = serializers.SerializerMethodField()
    current_warmup_action_label = serializers.SerializerMethodField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            self.fields["proxy"].queryset = Proxy.objects.filter(owner=request.user, is_active=True)
            self.fields["role_template"].queryset = AccountRoleTemplate.objects.filter(owner=request.user)

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
            "role",
            "role_template",
            "role_template_detail",
            "operational_role",
            "operational_role_label",
            "current_warmup_action_type",
            "current_warmup_action_status",
            "current_warmup_action_label",
            "birth_date",
            "avatar_url",
            "health_score",
            "liveness_score",
            "risk_level",
            "quarantine_until",
            "is_quarantined",
            "last_success_at",
            "last_error_at",
            "sleep_min_seconds",
            "sleep_max_seconds",
            "device_model",
            "system_version",
            "randomize_device_profile",
            "warmup_age_days",
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
            "avatar_url",
            "operational_role",
            "operational_role_label",
            "current_warmup_action_type",
            "current_warmup_action_status",
            "current_warmup_action_label",
            "health_score",
            "liveness_score",
            "risk_level",
            "quarantine_until",
            "is_quarantined",
            "warmup_age_days",
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

    def validate_role(self, value):
        return " ".join((value or "").strip().split())[:80]

    def validate_birth_date(self, value):
        if not value:
            return value
        today = timezone.localdate()
        age = today.year - value.year - ((today.month, today.day) < (value.month, value.day))
        if age < 13:
            raise serializers.ValidationError("Account owner must be at least 13 years old.")
        if age > 100:
            raise serializers.ValidationError("Birth date looks unrealistic.")
        return value

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

    def get_avatar_url(self, obj):
        draft = obj.profile_drafts.exclude(photo="").order_by("-applied_at", "-updated_at").first()
        if not draft or not draft.photo:
            return ""
        try:
            url = draft.photo.url
        except ValueError:
            return ""
        request = self.context.get("request")
        return request.build_absolute_uri(url) if request else url

    def get_role_template_detail(self, obj):
        if not obj.role_template_id:
            return None
        return {
            "id": obj.role_template_id,
            "name": obj.role_template.name,
            "prompt": obj.role_template.prompt,
        }

    def get_liveness_score(self, obj):
        return account_liveness_score(obj)

    def get_risk_level(self, obj):
        return account_risk_level(obj)

    def get_operational_role(self, obj):
        if self._has_running_parsing(obj):
            return "parsing"
        if self._has_running_warmup(obj):
            return "warmup"
        return "reserve"

    def get_operational_role_label(self, obj):
        if self._has_running_parsing(obj):
            return "Парсинг"
        if self._has_running_warmup(obj):
            return "Прогрів"
        return "Резерв"

    def get_warmup_age_days(self, obj):
        if not obj.created_at:
            return 0
        return max(0, (timezone.localdate() - timezone.localdate(obj.created_at)).days)

    def get_current_warmup_action_type(self, obj):
        action = self._current_warmup_action(obj)
        return action.action_type if action else ""

    def get_current_warmup_action_status(self, obj):
        action = self._current_warmup_action(obj)
        return action.status if action else ""

    def get_current_warmup_action_label(self, obj):
        action = self._current_warmup_action(obj)
        if not action:
            return ""
        return WARMUP_ACTION_STATUS_LABELS.get(action.action_type, action.get_action_type_display())

    def _has_running_warmup(self, obj):
        cached = getattr(obj, "_has_running_warmup", None)
        if cached is not None:
            return cached
        return obj.warmup_plans.filter(status="running").exists()

    def _has_running_parsing(self, obj):
        return bool(getattr(obj, "_has_running_parsing", False))

    def _current_warmup_action(self, obj):
        cached = getattr(obj, "_current_warmup_action_cache", None)
        if cached is not None:
            return cached or None

        from apps.warmup.models import WarmupAction

        base_qs = obj.warmup_actions.filter(plan__status="running")
        action = base_qs.filter(status=WarmupAction.Status.RUNNING).order_by("started_at", "scheduled_for", "id").first()
        if action is None:
            action = base_qs.filter(status=WarmupAction.Status.QUEUED).order_by("scheduled_for", "id").first()
        obj._current_warmup_action_cache = action or False
        return action

    def update(self, instance, validated_data):
        template = validated_data.get("role_template", serializers.empty)
        instance = super().update(instance, validated_data)
        if template is not serializers.empty:
            instance.role = template.name if template else ""
            instance.save(update_fields=["role"])
        return instance


class AccountRoleTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountRoleTemplate
        fields = ("id", "name", "prompt", "created_at", "updated_at")
        read_only_fields = ("created_at", "updated_at")

    def validate_name(self, value):
        value = " ".join((value or "").strip().split())
        if not value:
            raise serializers.ValidationError("Role template name is required.")
        return value[:80]

    def validate_prompt(self, value):
        value = (value or "").strip()
        if len(value) < 10:
            raise serializers.ValidationError("Prompt must be at least 10 characters.")
        if len(value) > 5000:
            raise serializers.ValidationError("Prompt is too long.")
        return value


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


class TelegramAccountCreateChannelSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=128)
    description = serializers.CharField(max_length=255, required=False, allow_blank=True)
    supergroup = serializers.BooleanField(required=False, default=False)

    def validate_title(self, value):
        value = " ".join((value or "").strip().split())
        if len(value) < 3:
            raise serializers.ValidationError("Channel title must be at least 3 characters.")
        return value

    def validate_description(self, value):
        return " ".join((value or "").strip().split())


class TelegramAccountSet2FASerializer(serializers.Serializer):
    current_password = serializers.CharField(max_length=255, required=False, allow_blank=True, trim_whitespace=False)
    new_password = serializers.CharField(min_length=8, max_length=255, trim_whitespace=False)
    hint = serializers.CharField(max_length=64, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)

    def validate_hint(self, value):
        return " ".join((value or "").strip().split())


class TelegramAccountDialogListSerializer(serializers.Serializer):
    limit = serializers.IntegerField(required=False, min_value=1, max_value=100, default=40)


class TelegramAccountChatMessagesSerializer(serializers.Serializer):
    chat_id = serializers.CharField(max_length=128)
    limit = serializers.IntegerField(required=False, min_value=1, max_value=100, default=50)

    def validate_chat_id(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("chat_id is required.")
        return value


class TelegramAccountSendMessageSerializer(serializers.Serializer):
    chat_id = serializers.CharField(max_length=128)
    text = serializers.CharField(max_length=4096, trim_whitespace=True)

    def validate_chat_id(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("chat_id is required.")
        return value

    def validate_text(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("Message text is required.")
        return value


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
    liveness_score = serializers.SerializerMethodField()
    risk_level = serializers.SerializerMethodField()

    class Meta:
        model = TelegramAccount
        fields = (
            "id",
            "label",
            "status",
            "health_score",
            "liveness_score",
            "risk_level",
            "quarantine_until",
            "is_quarantined",
            "last_success_at",
            "last_error_at",
            "sleep_min_seconds",
            "sleep_max_seconds",
            "device_model",
            "system_version",
            "randomize_device_profile",
            "last_auth_error",
            "recommended_pause_range",
            "recent_events",
        )

    def get_recent_events(self, obj):
        events = obj.health_events.all()[:10]
        return AccountHealthEventSerializer(events, many=True).data

    def get_recommended_pause_range(self, obj):
        return {"min_seconds": obj.sleep_min_seconds, "max_seconds": obj.sleep_max_seconds}

    def get_liveness_score(self, obj):
        return account_liveness_score(obj)

    def get_risk_level(self, obj):
        return account_risk_level(obj)
