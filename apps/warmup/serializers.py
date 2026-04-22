from __future__ import annotations

import re

from rest_framework import serializers

from apps.telegram_accounts.models import TelegramAccount
from apps.warmup.models import WarmupAction, WarmupLog, WarmupPlan, WarmupPolicy, WarmupTarget


ACTION_UI_LABELS = {
    WarmupAction.ActionType.JOIN_CHANNEL: ("🚪", "Вступ у канал/групу"),
    WarmupAction.ActionType.JOIN_FOLDER: ("📁", "Вступ через папку"),
    WarmupAction.ActionType.VIEW_DIALOGS: ("👀", "Перегляд діалогів"),
    WarmupAction.ActionType.CHANNEL_SCROLL: ("📜", "Прокрутка каналу"),
    WarmupAction.ActionType.READ: ("📖", "Читання постів"),
    WarmupAction.ActionType.MARK_READ: ("✅", "Позначення прочитаним"),
    WarmupAction.ActionType.MESSAGE_SEARCH: ("🔎", "Пошук повідомлень"),
    WarmupAction.ActionType.REACTION: ("💬", "Реакція на пост"),
    WarmupAction.ActionType.FORWARD_MESSAGE: ("↗️", "Пересилка"),
    WarmupAction.ActionType.SAVED_NOTE: ("📝", "Нотатка"),
    WarmupAction.ActionType.POLL_SCAN: ("📊", "Опитування"),
    WarmupAction.ActionType.VIDEO_SCAN: ("🎬", "Відео"),
    WarmupAction.ActionType.VOICE_SCAN: ("🎧", "Voice"),
    WarmupAction.ActionType.GIF_SEARCH: ("🖼️", "GIF"),
    WarmupAction.ActionType.STICKER_SCAN: ("🏷️", "Стікери"),
    WarmupAction.ActionType.INLINE_BOT_CHECK: ("🤖", "Inline-бот"),
    WarmupAction.ActionType.LINK_PREVIEW: ("🔗", "Preview посилань"),
    WarmupAction.ActionType.TYPING_SIMULATION: ("⌨️", "Набір тексту"),
    WarmupAction.ActionType.PROFILE_VIEW: ("👤", "Перегляд профілю"),
    WarmupAction.ActionType.SETTINGS_CHECK: ("⚙️", "Налаштування"),
    WarmupAction.ActionType.GRADUAL_PROFILE_CHECK: ("🪪", "Профіль"),
    WarmupAction.ActionType.EMOJI_STATUS_CHECK: ("🙂", "Emoji-status"),
    WarmupAction.ActionType.DRAFTS_CHECK: ("📄", "Чернетки"),
    WarmupAction.ActionType.NOTIFICATION_CHECK: ("🔔", "Сповіщення"),
    WarmupAction.ActionType.SCHEDULED_MESSAGE_CHECK: ("⏰", "Відкладене"),
    WarmupAction.ActionType.ARCHIVE_CHECK: ("🗄️", "Архів"),
    WarmupAction.ActionType.MUTE_CHECK: ("🔕", "Mute"),
}


TARGET_RE = re.compile(r"^(@[A-Za-z0-9_]{5,32}|https://t\.me/[A-Za-z0-9_+/\-]{5,160}|t\.me/[A-Za-z0-9_+/\-]{5,160})$")


def model_default(model, field_name):
    return model._meta.get_field(field_name).default


def normalize_name(value: str) -> str:
    value = " ".join((value or "").strip().split())
    if not value:
        raise serializers.ValidationError("Name is required.")
    return value


class WarmupPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = WarmupPolicy
        fields = (
            "id",
            "name",
            "behavior_profile",
            "daily_join_min",
            "daily_join_max",
            "delay_min_seconds",
            "delay_max_seconds",
            "read_min_seconds",
            "read_max_seconds",
            "reaction_probability",
            "max_reactions_per_day",
            "retry_min_seconds",
            "retry_max_seconds",
            "active_start_hour",
            "active_end_hour",
            "actions_per_hour",
            "actions_per_day",
            "messages_per_day",
            "session_duration_minutes",
            "random_breaks",
            "auto_adapt_limits",
            "progressive_ramp",
            "allow_folder_one_click",
            "allow_public_gradual_join",
            "allow_private_join",
            "enable_view_dialogs",
            "enable_channel_scroll",
            "enable_mark_read",
            "enable_message_search",
            "enable_forward_messages",
            "enable_saved_notes",
            "enable_poll_scan",
            "enable_video_scan",
            "enable_voice_scan",
            "enable_gif_search",
            "enable_sticker_scan",
            "enable_inline_bot_check",
            "enable_link_preview",
            "enable_typing_simulation",
            "enable_profile_view",
            "enable_settings_check",
            "enable_gradual_profile_check",
            "enable_emoji_status_check",
            "enable_drafts_check",
            "enable_notification_check",
            "enable_scheduled_message_check",
            "enable_archive_check",
            "enable_mute_check",
            "search_query",
            "inline_bot_username",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("created_at", "updated_at")

    def validate_name(self, value):
        return normalize_name(value)

    def validate_reaction_probability(self, value):
        if value > 100:
            raise serializers.ValidationError("Reaction probability must be between 0 and 100.")
        return value

    def validate_active_start_hour(self, value):
        if value > 23:
            raise serializers.ValidationError("Hour must be between 0 and 23.")
        return value

    def validate_active_end_hour(self, value):
        if value > 23:
            raise serializers.ValidationError("Hour must be between 0 and 23.")
        return value

    def validate_search_query(self, value):
        return " ".join((value or "").strip().split())[:120]

    def validate_inline_bot_username(self, value):
        value = (value or "").strip().lstrip("@")
        if value and not re.fullmatch(r"[A-Za-z0-9_]{3,64}", value):
            raise serializers.ValidationError("Inline bot username is invalid.")
        return value

    def validate(self, attrs):
        daily_min = attrs.get("daily_join_min", getattr(self.instance, "daily_join_min", 0))
        daily_max = attrs.get("daily_join_max", getattr(self.instance, "daily_join_max", 0))
        delay_min = attrs.get("delay_min_seconds", getattr(self.instance, "delay_min_seconds", 0))
        delay_max = attrs.get("delay_max_seconds", getattr(self.instance, "delay_max_seconds", 0))
        read_min = attrs.get("read_min_seconds", getattr(self.instance, "read_min_seconds", 0))
        read_max = attrs.get("read_max_seconds", getattr(self.instance, "read_max_seconds", 0))
        retry_min = attrs.get("retry_min_seconds", getattr(self.instance, "retry_min_seconds", 0))
        retry_max = attrs.get("retry_max_seconds", getattr(self.instance, "retry_max_seconds", 0))
        actions_per_hour = attrs.get("actions_per_hour", getattr(self.instance, "actions_per_hour", model_default(WarmupPolicy, "actions_per_hour")))
        actions_per_day = attrs.get("actions_per_day", getattr(self.instance, "actions_per_day", model_default(WarmupPolicy, "actions_per_day")))
        messages_per_day = attrs.get("messages_per_day", getattr(self.instance, "messages_per_day", model_default(WarmupPolicy, "messages_per_day")))
        session_duration_minutes = attrs.get(
            "session_duration_minutes",
            getattr(self.instance, "session_duration_minutes", model_default(WarmupPolicy, "session_duration_minutes")),
        )

        if daily_min < 1 or daily_max < 1 or daily_min > daily_max:
            raise serializers.ValidationError({"daily_join_max": "Daily join max must be >= min and both must be positive."})
        if daily_max > 50:
            raise serializers.ValidationError({"daily_join_max": "Daily join max cannot exceed hard limit 50."})
        if delay_min < 60 or delay_min > delay_max:
            raise serializers.ValidationError({"delay_max_seconds": "Delay max must be >= min; min delay is 60 seconds."})
        if read_min < 1 or read_min > read_max:
            raise serializers.ValidationError({"read_max_seconds": "Read max must be >= min."})
        if retry_min < 60 or retry_min > retry_max:
            raise serializers.ValidationError({"retry_max_seconds": "Retry max must be >= min; min retry is 60 seconds."})
        if actions_per_hour < 1 or actions_per_hour > 120:
            raise serializers.ValidationError({"actions_per_hour": "Actions/hour must be between 1 and 120."})
        if actions_per_day < actions_per_hour or actions_per_day > 500:
            raise serializers.ValidationError({"actions_per_day": "Actions/day must be >= actions/hour and <= 500."})
        if messages_per_day > actions_per_day:
            raise serializers.ValidationError({"messages_per_day": "Messages/day cannot exceed actions/day."})
        if session_duration_minutes < 5 or session_duration_minutes > 7 * 24 * 60:
            raise serializers.ValidationError({"session_duration_minutes": "Session duration must be between 5 minutes and 7 days."})
        return attrs


class WarmupTargetSerializer(serializers.ModelSerializer):
    class Meta:
        model = WarmupTarget
        fields = (
            "id",
            "title",
            "target_type",
            "visibility",
            "value",
            "status",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("created_at", "updated_at")

    def validate_title(self, value):
        return normalize_name(value)

    def validate_value(self, value):
        value = (value or "").strip()
        if not TARGET_RE.fullmatch(value):
            raise serializers.ValidationError("Use @channel or t.me/ link.")
        if value.startswith("t.me/"):
            return f"https://{value}"
        return value

    def validate(self, attrs):
        target_type = attrs.get("target_type", getattr(self.instance, "target_type", None))
        value = attrs.get("value", getattr(self.instance, "value", ""))
        if target_type == WarmupTarget.TargetType.FOLDER and "addlist/" not in value:
            raise serializers.ValidationError({"value": "Folder target must be a t.me/addlist/... link."})
        return attrs


class WarmupTargetBulkImportSerializer(serializers.Serializer):
    targets = serializers.CharField(max_length=20000)
    visibility = serializers.ChoiceField(choices=WarmupTarget.Visibility.choices, default=WarmupTarget.Visibility.PUBLIC)

    def validate_targets(self, value):
        raw_items: list[str] = []
        for chunk in value.replace(",", "\n").splitlines():
            item = chunk.strip()
            if item:
                raw_items.append(item)
        unique_items = list(dict.fromkeys(raw_items))
        if not unique_items:
            raise serializers.ValidationError("At least one target is required.")
        if len(unique_items) > 500:
            raise serializers.ValidationError("Bulk import limit is 500 targets at once.")

        validated_items: list[dict[str, str]] = []
        item_serializer = WarmupTargetSerializer()
        for item in unique_items:
            target_type = WarmupTarget.TargetType.FOLDER if "addlist/" in item else WarmupTarget.TargetType.CHANNEL
            try:
                normalized = item_serializer.validate_value(item)
            except serializers.ValidationError as exc:
                raise serializers.ValidationError(f"{item}: {exc.detail[0] if isinstance(exc.detail, list) else exc.detail}") from exc
            validated_items.append(
                {
                    "title": normalized.removeprefix("https://t.me/").removeprefix("@")[:255],
                    "target_type": target_type,
                    "value": normalized,
                }
            )
        return validated_items


class WarmupPlanSerializer(serializers.ModelSerializer):
    account_ids = serializers.PrimaryKeyRelatedField(
        source="accounts",
        queryset=TelegramAccount.objects.none(),
        many=True,
        write_only=True,
        required=True,
    )
    target_ids = serializers.PrimaryKeyRelatedField(
        source="targets",
        queryset=WarmupTarget.objects.none(),
        many=True,
        write_only=True,
        required=True,
    )
    policy = serializers.PrimaryKeyRelatedField(queryset=WarmupPolicy.objects.none())
    policy_name = serializers.CharField(source="policy.name", read_only=True)
    account_count = serializers.IntegerField(read_only=True)
    target_count = serializers.IntegerField(read_only=True)
    queued_count = serializers.IntegerField(read_only=True)
    succeeded_count = serializers.IntegerField(read_only=True)
    failed_count = serializers.IntegerField(read_only=True)
    skipped_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = WarmupPlan
        fields = (
            "id",
            "name",
            "policy",
            "policy_name",
            "account_ids",
            "target_ids",
            "account_count",
            "target_count",
            "queued_count",
            "succeeded_count",
            "failed_count",
            "skipped_count",
            "status",
            "started_at",
            "completed_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("status", "started_at", "completed_at", "created_at", "updated_at")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            self.fields["policy"].queryset = WarmupPolicy.objects.filter(owner=request.user, is_active=True)
            self.fields["account_ids"].child_relation.queryset = TelegramAccount.objects.filter(
                owner=request.user,
                is_attached=True,
            )
            self.fields["target_ids"].child_relation.queryset = WarmupTarget.objects.filter(
                owner=request.user,
                status=WarmupTarget.Status.ACTIVE,
            )

    def validate_name(self, value):
        return normalize_name(value)

    def validate(self, attrs):
        accounts = attrs.get("accounts") or []
        targets = attrs.get("targets") or []
        if not accounts:
            raise serializers.ValidationError({"account_ids": "At least one account is required."})
        if not targets:
            raise serializers.ValidationError({"target_ids": "At least one target is required."})
        for account in accounts:
            if not account.is_connected:
                raise serializers.ValidationError({"account_ids": f"{account.label} is not connected."})
        policy = attrs.get("policy")
        if policy:
            for target in targets:
                if target.target_type == WarmupTarget.TargetType.FOLDER and not policy.allow_folder_one_click:
                    raise serializers.ValidationError({"target_ids": "Selected policy does not allow folder one-click joins."})
                if target.visibility == WarmupTarget.Visibility.PRIVATE and not policy.allow_private_join:
                    raise serializers.ValidationError({"target_ids": "Selected policy does not allow private targets."})
        return attrs

    def create(self, validated_data):
        accounts = validated_data.pop("accounts")
        targets = validated_data.pop("targets")
        owner = validated_data.pop("owner", self.context["request"].user)
        plan = WarmupPlan.objects.create(owner=owner, **validated_data)
        plan.accounts.set(accounts)
        plan.targets.set(targets)
        return plan


class WarmupActionSerializer(serializers.ModelSerializer):
    account_label = serializers.CharField(source="account.label", read_only=True)
    plan_name = serializers.CharField(source="plan.name", read_only=True)
    target_title = serializers.CharField(source="target.title", read_only=True)
    target_value = serializers.CharField(source="target.value", read_only=True)
    action_label = serializers.SerializerMethodField()
    action_emoji = serializers.SerializerMethodField()

    class Meta:
        model = WarmupAction
        fields = (
            "id",
            "plan",
            "account",
            "account_label",
            "plan_name",
            "target",
            "target_title",
            "target_value",
            "action_type",
            "action_label",
            "action_emoji",
            "status",
            "scheduled_for",
            "delay_seconds",
            "celery_task_id",
            "attempt",
            "error",
            "metadata",
            "started_at",
            "finished_at",
            "created_at",
        )
        read_only_fields = fields

    def get_action_label(self, obj):
        return ACTION_UI_LABELS.get(obj.action_type, ("ℹ️", obj.action_type))[1]

    def get_action_emoji(self, obj):
        return ACTION_UI_LABELS.get(obj.action_type, ("ℹ️", obj.action_type))[0]


class WarmupActionClearSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(
        choices=(
            WarmupAction.Status.QUEUED,
            WarmupAction.Status.RUNNING,
            WarmupAction.Status.FAILED,
            WarmupAction.Status.SKIPPED,
            "all",
        ),
        default=WarmupAction.Status.QUEUED,
    )
    clear_logs = serializers.BooleanField(default=False)
    purge_redis = serializers.BooleanField(default=True)


class WarmupLogSerializer(serializers.ModelSerializer):
    account_label = serializers.CharField(source="account.label", read_only=True)
    action_type = serializers.CharField(source="action.action_type", read_only=True)

    class Meta:
        model = WarmupLog
        fields = (
            "id",
            "level",
            "message",
            "account",
            "account_label",
            "plan",
            "action",
            "action_type",
            "metadata",
            "created_at",
        )
        read_only_fields = fields


class WarmupOverviewSerializer(serializers.Serializer):
    policies = WarmupPolicySerializer(many=True)
    targets = WarmupTargetSerializer(many=True)
    plans = WarmupPlanSerializer(many=True)
    actions = WarmupActionSerializer(many=True)
    logs = WarmupLogSerializer(many=True)
    connected_accounts = serializers.IntegerField()
    running_plans = serializers.IntegerField()
    queued_actions = serializers.IntegerField()
    quarantined_accounts = serializers.IntegerField()
