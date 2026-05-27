from __future__ import annotations

from rest_framework import serializers

from apps.neuro_commenting.models import (
    NeuroCommentBlacklist,
    NeuroCommentJob,
    NeuroCommentLog,
    NeuroCommentPrompt,
)
from apps.telegram_accounts.serializers import TelegramAccountSerializer


class NeuroCommentPromptSerializer(serializers.ModelSerializer):
    class Meta:
        model = NeuroCommentPrompt
        fields = ["id", "name", "text", "is_system", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class NeuroCommentLogSerializer(serializers.ModelSerializer):
    account_label = serializers.CharField(source="account.label", read_only=True)

    class Meta:
        model = NeuroCommentLog
        fields = [
            "id", "level", "message", "account_label",
            "channel", "post_text", "comment_text", "prompt_name",
            "metadata", "created_at",
        ]


class NeuroCommentBlacklistSerializer(serializers.ModelSerializer):
    account_label = serializers.CharField(source="account.label", read_only=True, allow_null=True)

    class Meta:
        model = NeuroCommentBlacklist
        fields = ["id", "channel_username", "reason", "account_label", "created_at"]
        read_only_fields = ["id", "created_at"]


class NeuroCommentJobSerializer(serializers.ModelSerializer):
    log_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = NeuroCommentJob
        fields = [
            "id", "name", "accounts", "sources",
            "use_ai_prompt", "selected_prompts",
            "comment_mode", "keywords", "random_probability",
            "work_mode", "max_comments", "duration_minutes",
            "language_mode", "language",
            "write_as_channel", "write_as_channel_username",
            "auto_reply_enabled", "auto_reply_message",
            "first_message_strategy", "first_message_text", "first_message_edit_delay",
            "account_rotation", "rotation_every_n",
            "comment_delay_min", "comment_delay_max",
            "entry_delay_min", "entry_delay_max",
            "ai_protection", "protection_mode",
            "comments_sent", "status", "error",
            "started_at", "finished_at", "created_at", "updated_at",
            "log_count",
        ]
        read_only_fields = [
            "id", "comments_sent", "status", "error",
            "started_at", "finished_at", "created_at", "updated_at", "log_count",
        ]


class NeuroCommentOverviewSerializer(serializers.Serializer):
    jobs = NeuroCommentJobSerializer(many=True)
    logs = NeuroCommentLogSerializer(many=True)
    accounts = TelegramAccountSerializer(many=True)
    system_prompts = NeuroCommentPromptSerializer(many=True)
    user_prompts = NeuroCommentPromptSerializer(many=True)
    blacklist = NeuroCommentBlacklistSerializer(many=True)
    # Raw dict — covers totals + per-account / per-prompt / top-errors breakdowns
    # computed in services._neuro_commenting_stats. Shape may evolve, so we pass
    # it through unchanged rather than locking a schema here.
    stats = serializers.DictField(required=False)
