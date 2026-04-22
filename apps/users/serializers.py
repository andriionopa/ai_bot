from __future__ import annotations

from rest_framework import serializers

from apps.users.models import User
from apps.users.services.telegram import verify_telegram_auth_payload


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "email", "full_name", "telegram_id", "google_sub", "auth_provider")


class TelegramLoginSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    first_name = serializers.CharField(max_length=255)
    last_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    username = serializers.CharField(max_length=255, required=False, allow_blank=True)
    photo_url = serializers.URLField(required=False, allow_blank=True)
    auth_date = serializers.IntegerField()
    hash = serializers.CharField(max_length=255)

    def validate(self, attrs):
        verify_telegram_auth_payload(attrs)
        return attrs

