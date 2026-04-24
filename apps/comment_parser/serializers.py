from __future__ import annotations

import re

from rest_framework import serializers

from apps.comment_parser.models import CommentParserJob, CommentParserLog, ParsedCommenter
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


class CommentParserJobSerializer(serializers.ModelSerializer):
    account_ids = serializers.ListField(child=serializers.IntegerField(), write_only=True, required=False)
    accounts = TelegramAccountSerializer(many=True, read_only=True)
    result_count = serializers.IntegerField(read_only=True)
    log_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = CommentParserJob
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
            "post_limit",
            "comment_limit",
            "days_limit",
            "skip_bots",
            "skip_deleted",
            "skip_scam",
            "only_with_username",
            "only_with_photo",
            "only_premium",
            "only_active_users",
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
        post_limit = attrs.get("post_limit", getattr(self.instance, "post_limit", 50))
        comment_limit = attrs.get("comment_limit", getattr(self.instance, "comment_limit", 200))
        days_limit = attrs.get("days_limit", getattr(self.instance, "days_limit", 30))
        if post_limit < 1 or post_limit > 10000:
            raise serializers.ValidationError({"post_limit": "Ліміт постів має бути 1–10000."})
        if comment_limit < 1 or comment_limit > 5000:
            raise serializers.ValidationError({"comment_limit": "Ліміт коментарів має бути 1–5000."})
        if days_limit < 0 or days_limit > 365:
            raise serializers.ValidationError({"days_limit": "Фільтр по днях має бути 0–365."})
        return attrs

    def create(self, validated_data):
        accounts = validated_data.pop("_accounts", [])
        owner = validated_data.pop("owner", self.context["request"].user)
        job = CommentParserJob.objects.create(owner=owner, **validated_data)
        if accounts:
            job.accounts.set(accounts)
        return job

    def update(self, instance, validated_data):
        accounts = validated_data.pop("_accounts", None)
        instance = super().update(instance, validated_data)
        if accounts is not None:
            instance.accounts.set(accounts)
        return instance


class ParsedCommenterSerializer(serializers.ModelSerializer):
    class Meta:
        model = ParsedCommenter
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
            "comment_count",
            "first_comment_at",
            "last_comment_at",
            "matched_keywords",
            "sample_comment",
            "metadata",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class CommentParserLogSerializer(serializers.ModelSerializer):
    account_label = serializers.CharField(source="account.label", read_only=True, default="")

    class Meta:
        model = CommentParserLog
        fields = ("id", "job", "account", "account_label", "level", "message", "metadata", "created_at")
        read_only_fields = fields


class CommentParserOverviewSerializer(serializers.Serializer):
    jobs = CommentParserJobSerializer(many=True)
    results = ParsedCommenterSerializer(many=True)
    logs = CommentParserLogSerializer(many=True)
    accounts = TelegramAccountSerializer(many=True)
    templates = serializers.DictField(child=serializers.ListField(child=serializers.CharField()))
