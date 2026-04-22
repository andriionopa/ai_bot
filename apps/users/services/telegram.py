from __future__ import annotations

import hashlib
import hmac

from django.conf import settings
from rest_framework.exceptions import ValidationError


def build_telegram_check_string(payload: dict[str, object]) -> str:
    items = []
    for key, value in sorted(payload.items()):
        if key == "hash" or value in ("", None):
            continue
        items.append(f"{key}={value}")
    return "\n".join(items)


def verify_telegram_auth_payload(payload: dict[str, object]) -> None:
    bot_token = settings.TELEGRAM_BOT_TOKEN
    if not bot_token:
        raise ValidationError("Telegram bot token is not configured")

    secret = hashlib.sha256(bot_token.encode("utf-8")).digest()
    data_check_string = build_telegram_check_string(payload)
    digest = hmac.new(secret, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

    if digest != payload.get("hash"):
        raise ValidationError("Invalid Telegram auth signature")

