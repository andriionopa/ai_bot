from __future__ import annotations

from rest_framework import serializers

from apps.channel_parser.serializers import ChannelCollectionTemplateSerializer
from apps.reaction_bot.models import HARDCODED_EMOJIS, AccountChannelBinding, ReactionJob, ReactionLog
from apps.telegram_accounts.serializers import TelegramAccountSerializer


class AccountChannelBindingSerializer(serializers.ModelSerializer):
    account_label = serializers.CharField(source="account.label", read_only=True)

    class Meta:
        model = AccountChannelBinding
        fields = ["id", "account", "account_label", "channel_username", "title", "created_at"]
        read_only_fields = ["id", "account_label", "created_at"]


class ReactionLogSerializer(serializers.ModelSerializer):
    account_label = serializers.CharField(source="account.label", read_only=True)

    class Meta:
        model = ReactionLog
        fields = ["id", "level", "message", "metadata", "account_label", "created_at"]


class ReactionJobSerializer(serializers.ModelSerializer):
    log_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = ReactionJob
        fields = [
            "id", "name", "accounts", "sources",
            "emojis", "emoji_mode", "reaction_probability",
            "work_mode", "post_limit", "max_reactions", "duration_minutes",
            "reaction_delay_min", "reaction_delay_max",
            "entry_delay_min", "entry_delay_max",
            "ai_protection", "speed_mode",
            "use_channel_identity", "channel_bindings", "account_rotation",
            "use_subscriptions", "subscriptions_limit",
            "ai_smart_emoji", "react_to_comments", "comment_reaction_probability",
            "reactions_sent", "status", "error",
            "started_at", "finished_at", "created_at", "updated_at",
            "log_count",
        ]
        read_only_fields = ["id", "reactions_sent", "status", "error", "started_at", "finished_at", "created_at", "updated_at", "log_count"]


class ReactionOverviewSerializer(serializers.Serializer):
    jobs = ReactionJobSerializer(many=True)
    logs = ReactionLogSerializer(many=True)
    accounts = TelegramAccountSerializer(many=True)
    bindings = AccountChannelBindingSerializer(many=True)
    channel_templates = ChannelCollectionTemplateSerializer(many=True)
    hardcoded_emojis = serializers.ListField(child=serializers.CharField())
