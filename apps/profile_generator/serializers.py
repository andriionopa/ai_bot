from __future__ import annotations

from django.utils import timezone
from rest_framework import serializers

from apps.input_validation import validate_uploaded_image
from apps.profile_generator.models import ProfileDraft
from apps.telegram_accounts.models import TelegramAccount


def normalize_telegram_channel(value: str) -> str:
    value = " ".join(value.strip().split())
    if not value:
        raise serializers.ValidationError("Telegram channel is required.")
    if len(value) > 255:
        raise serializers.ValidationError("Telegram channel is too long.")
    if any(char.isspace() for char in value):
        raise serializers.ValidationError("Telegram channel must not contain whitespace.")
    if value.startswith("https://t.me/"):
        return value
    if value.startswith("http://t.me/"):
        return f"https://{value.removeprefix('http://')}"
    if value.startswith("t.me/"):
        return f"https://{value}"
    if value.startswith("@"):
        return value
    return f"@{value}"


def validate_birth_date_value(value):
    if not value:
        raise serializers.ValidationError("Birth date is required.")
    today = timezone.localdate()
    age = today.year - value.year - ((today.month, today.day) < (value.month, value.day))
    if age < 13 or age > 90:
        raise serializers.ValidationError("Age by birth date must be between 13 and 90.")
    return value


def normalize_short_text(value: str, *, field_name: str, max_length: int) -> str:
    value = " ".join((value or "").strip().split())
    if not value:
        raise serializers.ValidationError(f"{field_name} is required.")
    if len(value) > max_length:
        raise serializers.ValidationError(f"{field_name} is too long.")
    return value


class ProfileDraftSerializer(serializers.ModelSerializer):
    account_label = serializers.CharField(source="account.label", read_only=True)

    class Meta:
        model = ProfileDraft
        fields = (
            "id",
            "account",
            "account_label",
            "gender",
            "age",
            "birth_date",
            "country",
            "profession",
            "telegram_channel",
            "bio",
            "photo",
            "photo_prompt",
            "image_source",
            "status",
            "last_error",
            "provider_payload",
            "applied_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "account",
            "account_label",
            "age",
            "photo",
            "photo_prompt",
            "image_source",
            "status",
            "last_error",
            "provider_payload",
            "applied_at",
            "created_at",
            "updated_at",
        )

    def validate_birth_date(self, value):
        return validate_birth_date_value(value)

    def validate_country(self, value):
        return normalize_short_text(value, field_name="Country", max_length=120)

    def validate_profession(self, value):
        return normalize_short_text(value, field_name="Profession", max_length=120)

    def validate_telegram_channel(self, value):
        return normalize_telegram_channel(value)

    def validate_bio(self, value):
        if not value:
            return ""
        value = " ".join(value.strip().split())
        if len(value) > 70:
            raise serializers.ValidationError("Telegram bio must be 70 characters or less.")
        return value


class ProfileDraftCreateSerializer(serializers.ModelSerializer):
    photo = serializers.FileField(required=False, allow_empty_file=False)

    class Meta:
        model = ProfileDraft
        fields = ("account", "gender", "birth_date", "country", "profession", "telegram_channel", "bio", "photo")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            self.fields["account"].queryset = TelegramAccount.objects.filter(owner=request.user)

    def validate_telegram_channel(self, value):
        return normalize_telegram_channel(value)

    def validate_birth_date(self, value):
        return validate_birth_date_value(value)

    def validate_country(self, value):
        return normalize_short_text(value, field_name="Country", max_length=120)

    def validate_profession(self, value):
        return normalize_short_text(value, field_name="Profession", max_length=120)

    def validate_bio(self, value):
        if not value:
            return ""
        value = " ".join(value.strip().split())
        if len(value) > 70:
            raise serializers.ValidationError("Telegram bio must be 70 characters or less.")
        return value

    def validate_photo(self, value):
        validate_uploaded_image(value)
        return value

    def validate_account(self, value):
        if not value.is_connected:
            raise serializers.ValidationError("Only connected Telegram accounts can be used for profile drafts.")
        return value

    def create(self, validated_data):
        photo = validated_data.pop("photo", None)
        draft = ProfileDraft.objects.create(
            owner=self.context["request"].user,
            **validated_data,
        )
        if photo:
            draft.photo = photo
            draft.image_source = ProfileDraft.ImageSource.UPLOAD
            draft.status = ProfileDraft.Status.GENERATED
            draft.save(update_fields=["photo", "image_source", "status", "updated_at"])
        return draft


class ProfilePhotoUploadSerializer(serializers.Serializer):
    photo = serializers.FileField(allow_empty_file=False)

    def validate_photo(self, value):
        validate_uploaded_image(value)
        return value
