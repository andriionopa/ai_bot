from __future__ import annotations

import re

from rest_framework import serializers

from apps.channel_parser.models import (
    ChannelCollectionItem,
    ChannelCollectionTemplate,
    ChannelParserJob,
    ChannelParserLog,
    ChannelParserTemplate,
    ParsedChannel,
)
from apps.telegram_accounts.models import TelegramAccount
from apps.telegram_accounts.serializers import TelegramAccountSerializer


SYSTEM_KEYWORD_TEMPLATES = {
    "business": ["Бізнес", "Заробіток", "Бізнес Telegram", "Бізнес ідеї"],
    "crypto": ["Крипта", "Airdrop", "Crypto news", "Web3"],
    "ecommerce": ["Дропшипінг", "Товарка", "Маркетплейс", "Опт"],
}

LANGUAGE_CHOICES = {"ru", "uk", "be", "en", "tr", "es", "de", "fr", "it", "pt", "zh", "ja", "ar", "hi"}


def _normalize_words(value) -> list[str]:
    if isinstance(value, str):
        raw_items = re.split(r"[,;\n]+", value)
    else:
        raw_items = value or []
    items = []
    for item in raw_items:
        item = " ".join(str(item or "").strip().split())
        if item and item not in items:
            items.append(item[:80])
    return items


class ChannelParserJobSerializer(serializers.ModelSerializer):
    account_ids = serializers.ListField(child=serializers.IntegerField(), write_only=True, required=False)
    accounts = TelegramAccountSerializer(many=True, read_only=True)
    result_count = serializers.IntegerField(read_only=True)
    log_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = ChannelParserJob
        fields = (
            "id",
            "name",
            "accounts",
            "account_ids",
            "keywords",
            "suffixes",
            "parse_type",
            "search_scope",
            "ai_protection",
            "fast_mode",
            "speed_mode",
            "activity_filter",
            "comments_filter",
            "result_limit",
            "subscriber_min",
            "subscriber_max",
            "rating_min",
            "language_detection",
            "languages",
            "request_delay_seconds",
            "channel_delay_seconds",
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

    def validate_keywords(self, value):
        items = _normalize_words(value)
        if not items:
            raise serializers.ValidationError("Додайте хоча б одне ключове слово.")
        if len(items) > 50:
            raise serializers.ValidationError("Максимум 50 ключових слів.")
        return items

    def validate_suffixes(self, value):
        items = _normalize_words(value)
        if len(items) > 50:
            raise serializers.ValidationError("Максимум 50 закінчень.")
        return items

    def validate_languages(self, value):
        items = [str(item).strip().lower() for item in (value or []) if str(item).strip()]
        invalid = [item for item in items if item not in LANGUAGE_CHOICES]
        if invalid:
            raise serializers.ValidationError(f"Невідомі мови: {', '.join(invalid)}")
        return list(dict.fromkeys(items))

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

        result_limit = attrs.get("result_limit", getattr(self.instance, "result_limit", 50))
        if result_limit < 1 or result_limit > 5000:
            raise serializers.ValidationError({"result_limit": "Ліміт результатів має бути 1-5000."})
        subscriber_min = attrs.get("subscriber_min", getattr(self.instance, "subscriber_min", 0))
        subscriber_max = attrs.get("subscriber_max", getattr(self.instance, "subscriber_max", 0))
        if subscriber_min > subscriber_max:
            raise serializers.ValidationError({"subscriber_max": "Максимум підписників має бути >= мінімум."})
        rating_min = attrs.get("rating_min", getattr(self.instance, "rating_min", 0))
        if rating_min > 10:
            raise serializers.ValidationError({"rating_min": "Рейтинг має бути 0-10."})
        return attrs

    def create(self, validated_data):
        accounts = validated_data.pop("_accounts", [])
        owner = validated_data.pop("owner", self.context["request"].user)
        job = ChannelParserJob.objects.create(owner=owner, **validated_data)
        if accounts:
            job.accounts.set(accounts)
        return job

    def update(self, instance, validated_data):
        accounts = validated_data.pop("_accounts", None)
        instance = super().update(instance, validated_data)
        if accounts is not None:
            instance.accounts.set(accounts)
        return instance


class ChannelParserTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChannelParserTemplate
        fields = (
            "id",
            "name",
            "keywords",
            "suffixes",
            "parse_type",
            "search_scope",
            "ai_protection",
            "fast_mode",
            "speed_mode",
            "activity_filter",
            "comments_filter",
            "result_limit",
            "subscriber_min",
            "subscriber_max",
            "rating_min",
            "language_detection",
            "languages",
            "request_delay_seconds",
            "channel_delay_seconds",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("created_at", "updated_at")

    def validate_keywords(self, value):
        items = _normalize_words(value)
        if not items:
            raise serializers.ValidationError("Додайте хоча б одне ключове слово.")
        if len(items) > 50:
            raise serializers.ValidationError("Максимум 50 ключових слів.")
        return items

    def validate_suffixes(self, value):
        items = _normalize_words(value)
        if len(items) > 50:
            raise serializers.ValidationError("Максимум 50 закінчень.")
        return items

    def validate_languages(self, value):
        items = [str(item).strip().lower() for item in (value or []) if str(item).strip()]
        invalid = [item for item in items if item not in LANGUAGE_CHOICES]
        if invalid:
            raise serializers.ValidationError(f"Невідомі мови: {', '.join(invalid)}")
        return list(dict.fromkeys(items))


class ChannelCollectionItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChannelCollectionItem
        fields = (
            "id",
            "template",
            "source_job",
            "title",
            "username",
            "url",
            "telegram_id",
            "entity_type",
            "subscribers",
            "rating",
            "language",
            "activity_level",
            "comments_open",
            "matched_query",
            "description",
            "metadata",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class ChannelCollectionTemplateSerializer(serializers.ModelSerializer):
    item_count = serializers.IntegerField(read_only=True)
    items = serializers.SerializerMethodField()

    class Meta:
        model = ChannelCollectionTemplate
        fields = ("id", "name", "item_count", "items", "created_at", "updated_at")
        read_only_fields = ("created_at", "updated_at", "item_count", "items")

    def validate_name(self, value):
        name = " ".join(str(value or "").strip().split())
        if not name:
            raise serializers.ValidationError("Вкажіть назву шаблону каналів.")
        return name[:255]

    def get_items(self, obj):
        items = getattr(obj, "_prefetched_items", None)
        if items is None:
            items = list(obj.items.order_by("title", "id")[:30])
        return ChannelCollectionItemSerializer(items, many=True).data


class ParsedChannelSerializer(serializers.ModelSerializer):
    class Meta:
        model = ParsedChannel
        fields = (
            "id",
            "job",
            "title",
            "username",
            "url",
            "telegram_id",
            "entity_type",
            "subscribers",
            "rating",
            "language",
            "activity_level",
            "comments_open",
            "last_post_at",
            "matched_query",
            "description",
            "metadata",
            "created_at",
        )
        read_only_fields = fields


class ChannelParserLogSerializer(serializers.ModelSerializer):
    account_label = serializers.CharField(source="account.label", read_only=True, default="")

    class Meta:
        model = ChannelParserLog
        fields = ("id", "job", "account", "account_label", "level", "message", "metadata", "created_at")
        read_only_fields = fields


class ChannelParserOverviewSerializer(serializers.Serializer):
    jobs = ChannelParserJobSerializer(many=True)
    results = ParsedChannelSerializer(many=True)
    logs = ChannelParserLogSerializer(many=True)
    accounts = TelegramAccountSerializer(many=True)
    templates = serializers.DictField(child=serializers.ListField(child=serializers.CharField()))
    parser_templates = ChannelParserTemplateSerializer(many=True)
    channel_templates = ChannelCollectionTemplateSerializer(many=True)
