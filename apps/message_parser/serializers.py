from __future__ import annotations

import re

from rest_framework import serializers

from apps.channel_parser.serializers import ChannelCollectionTemplateSerializer
from apps.message_parser.models import MessageParserJob, MessageParserLog, ParsedUser
from apps.telegram_accounts.models import TelegramAccount
from apps.telegram_accounts.serializers import TelegramAccountSerializer


SYSTEM_KEYWORD_TEMPLATES = {
    "sales": ["товарка", "дропшипінг", "маркетплейс"],
    "crypto": ["крипта", "криптогаманець", "airdrop"],
    "growth": ["розкрутити Telegram-канал", "ліди", "реклама"],
}


def _normalize_words(value) -> list[str]:
    if isinstance(value, str):
        raw_items = re.split(r"[,;\n]+", value)
    else:
        raw_items = value or []
    items = []
    for item in raw_items:
        item = " ".join(str(item or "").strip().split())
        if item and item not in items:
            items.append(item[:255])
    return items


def _normalize_sources(value) -> list[str]:
    sources = _normalize_words(value)
    if len(sources) > 500:
        raise serializers.ValidationError("Максимум 500 джерел.")
    return sources


class MessageParserJobSerializer(serializers.ModelSerializer):
    account_ids = serializers.ListField(child=serializers.IntegerField(), write_only=True, required=False)
    accounts = TelegramAccountSerializer(many=True, read_only=True)
    result_count = serializers.IntegerField(read_only=True)
    log_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = MessageParserJob
        fields = (
            "id",
            "name",
            "accounts",
            "account_ids",
            "sources",
            "keywords",
            "ai_protection",
            "fast_mode",
            "speed_mode",
            "message_limit",
            "days_limit",
            "skip_bots",
            "skip_deleted",
            "skip_scam",
            "only_with_username",
            "only_with_photo",
            "only_premium",
            "only_active_users",
            "include_forwards",
            "include_replies",
            "status",
            "error",
            "started_at",
            "finished_at",
            "created_at",
            "updated_at",
            "result_count",
            "log_count",
        )
        read_only_fields = ("status", "error", "started_at", "finished_at", "created_at", "updated_at")

    def validate_sources(self, value):
        items = _normalize_sources(value)
        if not items:
            raise serializers.ValidationError("Додайте хоча б одне джерело.")
        return items

    def validate_keywords(self, value):
        items = _normalize_words(value)
        if len(items) > 100:
            raise serializers.ValidationError("Максимум 100 ключових слів.")
        return items

    def validate(self, attrs):
        request = self.context.get("request")
        account_ids = attrs.pop("account_ids", None)
        if account_ids is not None:
            attrs["_accounts"] = list(
                TelegramAccount.objects.filter(
                    owner=request.user,
                    pk__in=list(dict.fromkeys(account_ids)),
                    is_attached=True,
                    auth_state=TelegramAccount.AuthState.CONNECTED,
                )
            )
            if not attrs["_accounts"]:
                raise serializers.ValidationError({"account_ids": "Виберіть хоча б один валідний акаунт."})
        message_limit = attrs.get("message_limit", getattr(self.instance, "message_limit", 1000))
        days_limit = attrs.get("days_limit", getattr(self.instance, "days_limit", 30))
        if message_limit < 1 or message_limit > 100000:
            raise serializers.ValidationError({"message_limit": "Ліміт повідомлень має бути 1-100000."})
        if days_limit < 0 or days_limit > 365:
            raise serializers.ValidationError({"days_limit": "Фільтр по днях має бути 0-365."})
        return attrs

    def create(self, validated_data):
        accounts = validated_data.pop("_accounts", [])
        owner = validated_data.pop("owner", self.context["request"].user)
        job = MessageParserJob.objects.create(owner=owner, **validated_data)
        if accounts:
            job.accounts.set(accounts)
        return job

    def update(self, instance, validated_data):
        accounts = validated_data.pop("_accounts", None)
        instance = super().update(instance, validated_data)
        if accounts is not None:
            instance.accounts.set(accounts)
        return instance


class ParsedUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = ParsedUser
        fields = (
            "id",
            "job",
            "source_ref",
            "source_title",
            "source_username",
            "source_url",
            "telegram_user_id",
            "username",
            "full_name",
            "profile_url",
            "is_bot",
            "is_deleted",
            "is_scam",
            "is_premium",
            "has_photo",
            "message_count",
            "first_message_at",
            "last_message_at",
            "matched_keywords",
            "sample_message",
            "metadata",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class MessageParserLogSerializer(serializers.ModelSerializer):
    account_label = serializers.CharField(source="account.label", read_only=True, default="")

    class Meta:
        model = MessageParserLog
        fields = ("id", "job", "account", "account_label", "level", "message", "metadata", "created_at")
        read_only_fields = fields


class MessageParserOverviewSerializer(serializers.Serializer):
    jobs = MessageParserJobSerializer(many=True)
    results = ParsedUserSerializer(many=True)
    logs = MessageParserLogSerializer(many=True)
    accounts = TelegramAccountSerializer(many=True)
    channel_templates = ChannelCollectionTemplateSerializer(many=True)
    templates = serializers.DictField(child=serializers.ListField(child=serializers.CharField()))
